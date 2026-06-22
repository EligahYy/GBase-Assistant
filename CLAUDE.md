# CLAUDE.md — GBase 8a Assistant

> Claude Code 项目指南。架构、规范、关键文件以本文为准。

## 项目定位

面向 GBase 8a MPP 数据库的中文 AI 助手。核心能力：
- **NL2SQL**：自然语言 → Query IR → Schema Grounding → GBase SQL 生成 + 沙箱执行
- **知识问答**：官方产品手册 + 向量检索 + ripgrep 全文降级 + RRF 融合
- **连接管理**：GBase 数据库连接状态 SSE 实时推送

## 技术栈

| 层 | 技术 |
|---|---|
| 编排 | **LangGraph** StateGraph（v3.4 Semantic NL2SQL Graph） |
| 事件协议 | **AG-UI** 标准 SSE（单 FastAPI 进程，无需 Node.js 中间层） |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy async + SQLite |
| LLM | LiteLLM（DeepSeek/Qwen/GPT-4o fallback） |
| 向量库 | Qdrant（schemas / knowledge / error_codes） |
| 前端 | Vue 3 + Naive UI + Pinia + TypeScript |
| SQL 解析 | sqlglot + 自定义 GBase 8a 规则 + SQLSandbox |

## 系统架构

```
Vue 3 / Pinia / Naive UI
          |
          | POST /api/chat/stream (AG-UI SSE)
          v
FastAPI Chat Gateway
          |
          +-- 问候 ----------> 低延迟受限 LLM 回复
          +-- 监控 ----------> GetDatabaseStatusTool 快速路径
          +-- 知识问答 ------> KnowledgeAgent 快速路径
          |
          +-- 数据查询 ------> v3.4 Semantic NL2SQL Graph
                                  |
                                  v
 resolve -> build_context -> plan_query -> clarify / generate_sql
                                  |                    |
                                  +----------> verify_sql <-> refine_sql
                                                       |
                                                       v
                                                   execute_sql
                                                       |
                                                       v
                                                   build_answer
```

**v3.4 核心特性：**
- **确定性状态图**：基于 LangGraph 的受控 pipeline，非自由循环 ReAct。
- **语义层约束**：Query IR 严格绑定到 SemanticModel / 聚焦 Schema，模型不能自行发明业务定义。
- **混合语义匹配**：结合词法匹配、别名、字符相似度、描述和可选向量相似度召回指标/维度/成员。
- **有界自动修复**：最多 4 个 SQL 候选、2 次数据库执行、同类错误最多重试 2 次。
- **快速路径**：问候、监控、知识问答绕过 NL2SQL 图，直接返回。
- **Anti-Hallucination**：知识检索返回 `found/partial/not_found` 状态，Prompt 强制 LLM 遵守。
- **AG-UI STATE_DELTA**：SQL/结果/图表配置通过标准 SSE 事件实时推送前端。

## 项目结构

```
gbase8a-assistant/
├── backend/app/
│   ├── agents/
│   │   ├── graph.py               # v3.4 NL2SQL 图、快速路径与 AG-UI Runner
│   │   ├── state.py               # AgentState TypedDict
│   │   ├── schema_graph.py        # Schema 知识图谱（DDL 解析、关系推断）
│   │   ├── agents/
│   │   │   ├── knowledge_agent.py # 知识问答 Pipeline（search → answer）
│   │   │   └── __init__.py
│   │   └── tools/
│   │       ├── base.py            # ToolParameter 元数据
│   │       ├── sql_tools.py       # SubmitSQLTool（execute_sql 节点使用）
│   │       └── status_tool.py     # GetDatabaseStatusTool（monitoring 快速路径）
│   ├── gateway/
│   │   └── ag_ui_encoder.py       # AG-UI 8 种标准 SSE 事件编码
│   ├── api/
│   │   ├── chat.py                # /api/chat/stream + 对话/文件夹/批量/反馈
│   │   ├── connections.py         # 连接管理 + SSE 状态流
│   │   ├── semantic_models.py     # 语义模型、指标、维度、JOIN 管理
│   │   ├── knowledge.py           # 知识库文档管理
│   │   ├── admin.py               # reindex / reindex-pdf / reindex-web / feedback-stats
│   │   └── tools.py               # 错误码查询工具接口
│   ├── semantic/
│   │   ├── context_builder.py     # 语义上下文、FocusedSchema、可信 JOIN
│   │   ├── matcher.py             # 混合语义匹配
│   │   ├── models.py              # 语义层 ORM 模型
│   │   ├── planner.py             # 自然语言 → 受约束 Query IR
│   │   ├── query_ir.py            # 结构化查询意图
│   │   └── schema_assets.py       # 无业务模型时的 Schema 推断资产
│   ├── knowledge/
│   │   ├── document_chunker.py    # PDF 缓存 + MD 切片 + Qdrant 索引
│   │   ├── web_crawler.py         # Playwright gbase.cn 爬虫
│   │   └── loader.py              # 方言规则加载
│   ├── llm/                       # LiteLLM 客户端 + LangChain 适配器
│   ├── sql/                       # 语义验证、方言验证、沙箱
│   ├── vector/                    # Qdrant 客户端 + 检索 + 索引
│   ├── services/                  # conversation_service、connection_health_checker 等
│   └── db_connectors/             # GBase 原生驱动适配 + SQLite 演示驱动
├── frontend/src/
│   ├── composables/               # useSSE / useAGUIClient / useTheme
│   ├── stores/                    # Pinia（chat、connection、theme）
│   ├── api/                       # Axios 客户端
│   └── components/chat/           # ChatPanel、MessageBubble、SQL/图表/表格
├── knowledge/                     # 官方 PDF 手册 + dialect_rules
└── deploy/                        # Docker Compose
```

## 核心链路

### NL2SQL（v3.4 Semantic Graph）

```
用户输入 → 意图分类
  → 数据查询 → resolve → build_context → plan_query
    → clarify → END（存在歧义）
    → generate_sql → verify_sql
      → 失败 → refine_sql → verify_sql（有界循环）
      → 成功 → execute_sql → build_answer → AG-UI SSE
```

`verify_sql` 依次检查：语义一致性、只读安全、单语句、方言、Schema 引用。

### 知识问答

```
用户输入 → 意图分类 → knowledge 快速路径
  → HybridKnowledgeRetriever（ripgrep + Qdrant + RRF + 扩展查询回退）
  → KnowledgeAgent 基于 status 决定回答策略
  → AG-UI SSE 输出（注明来源/标记推测/诚实说不知道）
```

## 运行命令

```bash
make install          # 安装前后端依赖
make dev-backend      # 后端 http://localhost:8000
make dev-frontend     # 前端 http://localhost:5173
make test             # 后端测试（TESTING=1 跳过 Qdrant/Embedding）
make lint             # ruff 代码检查
make migrate          # 数据库迁移
```

### Admin API

```bash
# PDF 产品手册索引（首次 ~5min 提取，后续秒级）
curl -X POST http://localhost:8000/api/admin/reindex-pdf

# JSON 知识库索引
curl -X POST http://localhost:8000/api/admin/reindex
```

## 环境变量

`backend/.env` 核心变量：

```bash
DEEPSEEK_API_KEY=sk-xxx
DEFAULT_MODEL=deepseek/deepseek-chat
SECRET_KEY=xxx          # 数据库密码加密，不设则重启后密码失效
SKIP_VECTOR_SYNC=true   # debug 模式跳过知识库同步
QDRANT_URL=http://localhost:6333
ADMIN_TOKEN=xxx         # 管理接口 Token；未配置时 DEBUG=true 允许无 Token
```

## 编码规范

**Python:**
- 公共函数必须有类型注解；LLM/DB 操作必须 async/await。
- LLM 调用统一经过 `LiteLLMClientImpl` / `LLMClient` Protocol。
- LangGraph 节点只写自己的 AgentState 字段（字段所有权隔离）。
- ruff：行宽 120、双引号、导入排序。

**Vue/TypeScript:**
- `<script setup lang="ts">`，Props/Emits 使用 `defineProps<T>()` / `defineEmits<T>()`。
- Pinia Setup Store；API 调用集中在 `frontend/src/api/`。
- 优先 Naive UI；禁止引入新 CSS 框架。

## 测试

- `TESTING=1` 跳过 Qdrant/Embedding 初始化。
- 涉及 LLM API 的测试必须 Mock。
- 后端测试覆盖 agents / API / validator / sandbox / crypto / semantic matcher。

## 安全边界

- SQL 执行只允许只读查询（`SQLSandbox` AST + 字符串双重校验）。
- 生产必须配套数据库账号层只读权限 + SQL 执行审计。
- `.env` 不得提交，`.env.example` 只能使用假值。

## 版本说明

- 当前主线为 **v3.4 Semantic NL2SQL Graph**。
- v3.2 时期的统一 ReAct Agent 工具（`schema_tools.py`、`knowledge_tools.py`、`error_code_tool.py`、`glossary_tool.py`、`ExecuteSQLTool`、`unified_agent.py`、`prompts.py`）已清理删除，不再维护。
