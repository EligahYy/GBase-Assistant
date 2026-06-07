# CLAUDE.md — GBase 8a Assistant

> Claude Code 项目指南。架构、规范、关键文件以本文为准。

## 项目定位

面向 GBase 8a MPP 数据库的中文 AI 助手。核心能力：
- **NL2SQL**：自然语言 → Schema Grounding → GBase SQL 生成 + 沙箱执行
- **知识问答**：官方产品手册 + 向量检索 + RRF 融合
- **连接管理**：GBase 数据库连接状态 SSE 实时推送

## 技术栈

| 层 | 技术 |
|---|---|
| 编排 | **LangGraph** StateGraph + AgentState（Unified ReAct Agent 模式） |
| 事件协议 | **AG-UI** 标准 SSE（单 FastAPI 进程，无需 Node.js 中间层） |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy async + SQLite |
| LLM | LiteLLM（DeepSeek/Qwen/GPT-4o fallback） |
| 向量库 | Qdrant（schemas / knowledge / error_codes） |
| 前端 | Vue 3 + Naive UI + Pinia + TypeScript |
| SQL 解析 | sqlglot + 自定义 GBase 8a 方言 + 沙箱执行 |

## 系统架构

```
Vue 3 Chat UI ←── AG-UI SSE ──→ FastAPI Gateway
                                     │
                         LangGraph Unified ReAct Agent (v3.2)
                                     │
                    统一 Agent（全工具集，自主决策路由）
                     │                              │
                     │  submit_sql            final_answer
                     ↓                              ↓
              Validate Gate → Execute Gate        END
```

**v3.2 统一 Agent 架构：** 无独立 Supervisor/router。统一 Agent 持有全部 10 个工具，Prompt + Tools 即为路由机制。`final_answer` 工具提供显式终止信号防无限循环。循环检测 + 三级终止策略（温和提醒 → 紧急提示 → 优雅降级）确保健壮终止。

**v3.2 核心特性：**
- **统一 ReAct Agent**：单个 Agent 持有全部工具（Schema 探索 / SQL 提交 / 知识检索 / 监控 / final_answer），模型自主决策调用顺序
- **无路由错误**：不依赖 LLM 分类路由，模型根据完整上下文 + 工具描述自行判断
- **天然多意图**：Agent 可在同一轮调用 schema 工具 + knowledge 工具，解决 "查数据并解释概念" 类复合请求
- **final_answer 显式终止**：Agent 必须调用 `final_answer` 结束，避免"不知道何时停止"的循环问题
- **循环检测**：检测同一工具 + 同一参数的重复调用，注入停止提示
- **三级终止策略**：L1 温和提醒(8轮) → L2 紧急提示(10轮) → L3 优雅降级(12轮)
- **确定性 SQL Gate**：候选 SQL 必须通过只读安全、方言和 Schema 验证后才允许执行
- **监控快速路径**：数据库状态查询直接短路，绕过 Agent 图
- **Anti-Hallucination**：search_knowledge 返回 status (found/partial/not_found)，Prompt 强制 LLM 遵守
- **AG-UI STATE_DELTA**：SQL/结果/图表配置通过标准 SSE 事件实时推送前端

## 项目结构

```
gbase8a-assistant/
├── backend/app/
│   ├── agents/             # LangGraph v3.2 统一 Agent
│   │   ├── state.py        # AgentState TypedDict（namespace 隔离）
│   │   ├── agents/         # Agent 定义
│   │   │   ├── unified_agent.py  # 统一 Agent（prompt + 10 工具注册 + FinalAnswerTool）
│   │   │   ├── knowledge_agent.py # Knowledge Pipeline（search→answer，非 ReAct）
│   │   │   └── prompts.py        # 旧 prompt 占位（已迁移到各 agent 模块）
│   │   ├── tools/          # 统一 Agent 工具集
│   │   │   ├── schema_tools.py   # SearchSchemas / GetTableProfile / FindJoinPath
│   │   │   ├── sql_tools.py      # SubmitSQL / ExecuteSQL
│   │   │   ├── knowledge_tools.py # SearchKnowledgeTool
│   │   │   ├── glossary_tool.py  # QueryGlossary
│   │   │   ├── error_code_tool.py # LookupErrorCode
│   │   │   ├── status_tool.py    # GetDatabaseStatus
│   │   │   └── base.py           # ToolParameter 元数据
│   │   ├── schema_graph.py # Schema Knowledge Graph（DDL解析+角色+关系+检索）
│   │   └── graph.py        # v3.2 图（5节点）+ AG-UI Runner
│   ├── gateway/
│   │   └── ag_ui_encoder.py # AG-UI 8 种标准 SSE 事件编码
│   ├── api/
│   │   ├── chat.py         # /api/chat/stream（AG-UI 多智能体）+ 对话 CRUD + 文件夹 CRUD + 批量操作
│   │   ├── connections.py  # 连接管理 + SSE 状态流
│   │   ├── admin.py        # reindex / reindex-pdf / reindex-web
│   │   └── ...
│   ├── knowledge/
│   │   ├── document_chunker.py  # PDF 缓存 + MD 切片 + Qdrant 索引
│   │   ├── web_crawler.py       # Playwright gbase.cn 爬虫
│   │   └── loader.py            # 方言规则加载
│   ├── llm/                # LiteLLM 客户端 + LangChain 适配器
│   ├── sql/                # validator + sandbox
│   ├── vector/             # Qdrant 客户端 + 检索 + 索引
│   ├── services/           # conversation_service, connection_health_checker 等
│   └── db_connectors/      # GBase 原生驱动适配
├── frontend/src/
│   ├── composables/        # useSSE / useAGUIClient / useTheme
│   ├── stores/             # Pinia（chat, connection）
│   └── api/                # Axios 客户端
├── knowledge/              # 官方 PDF 手册 + dialect_rules + v1_archive
└── deploy/                 # Docker Compose
```

## 核心链路

### NL2SQL（v3.2 统一 Agent）

```
用户输入 → 统一 Agent(工具自主探索 → submit_sql)
  → Validate Gate(只读安全 + 方言 + Schema)
  → 失败则返回结构化错误并定向修复(最多3轮) → Execute Gate(沙箱)
  → Agent 调用 final_answer 输出结果 → AG-UI SSE 响应
```

### 知识问答

```
用户输入 → 统一 Agent(调用 search_knowledge)
  → HybridKnowledgeRetriever(精确ripgrep+语义Qdrant+RRF融合+关键词扩展回退)
  → 返回 chunks + status(found/partial/not_found) → Agent 基于 status 决定回答策略
  → final_answer 输出（注明来源/标记推测/诚实说不知道）→ AG-UI SSE 响应
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
```

## 编码规范

**Python:**
- 公共函数必须有类型注解；LLM/DB 操作必须 async/await
- LLM 调用统一经过 `LiteLLMClientImpl` / `LLMClient` Protocol
- LangGraph 节点只写自己的 AgentState 字段（字段所有权隔离）
- ruff：行宽 120、双引号、导入排序

**Vue/TypeScript:**
- `<script setup lang="ts">`，Props/Emits 使用 `defineProps<T>()` / `defineEmits<T>()`
- Pinia Setup Store；API 调用集中在 `frontend/src/api/`
- 优先 Naive UI；禁止引入新 CSS 框架

## 测试

- `TESTING=1` 跳过 Qdrant/Embedding 初始化
- 涉及 LLM API 的测试必须 Mock
- 182 个后端测试，覆盖 agents / API / validator / sandbox / crypto

## 安全边界

- SQL 执行只允许只读查询（`SQLSandbox` AST + 字符串双重校验）
- 生产必须配套数据库账号层只读权限 + SQL 执行审计
- `.env` 不得提交，`.env.example` 只能使用假值
