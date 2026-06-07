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
| 编排 | **LangGraph** StateGraph + AgentState（Planner-Specialist 模式） |
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
                        LangGraph Hybrid Multi-Agent (v3)
                                     │
                               Planner Agent
                        (多任务计划 + 顺序调度队列)
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
             SQL Specialist   Knowledge Pipeline  General Agent
             探索→submit_sql    Hybrid RAG→回答       通用对话
                    │
             Validate Gate → Execute Gate
```

**v3 混合多智能体架构：** Planner 负责任务分解与调度，Specialist 负责领域推理，SQL 验证和执行由确定性 Gate 接管。上下文通过 `AgentState` TypedDict namespace 隔离。

**v3 核心特性：**
- **Planner + Specialist 队列**：一次规划多个任务，框架顺序调度 SQL / Knowledge / General
- **确定性 SQL Gate**：候选 SQL 必须通过只读安全、方言和 Schema 验证后才允许执行
- **监控快速路径**：数据库状态查询直接短路，绕过 NL2SQL pipeline
- **项目文件夹**：对话分组管理 + 批量操作（归档/删除/移动）
- **多轮对话**：`build_context()` 加载历史消息，支持上下文连贯问答
- **AG-UI STATE_DELTA**：SQL/结果/图表配置通过标准 SSE 事件实时推送前端
- **LiteLLM Chat Adapter**：`_LiteLLMChatAdapter` 将 `LiteLLMClientImpl` 封装为 LangChain `BaseChatModel`

## 项目结构

```
gbase8a-assistant/
├── backend/app/
│   ├── agents/             # LangGraph v3 混合多智能体
│   │   ├── state.py        # AgentState TypedDict（namespace 隔离）
│   │   ├── agents/         # Planner / SQL / General Specialist
│   │   ├── tools/          # Specialist 显式工具集
│   │   ├── schema_graph.py # Schema Knowledge Graph（DDL解析+角色+关系+检索）
│   │   └── graph.py        # 协作调度图 + 确定性 Gate + AG-UI Runner
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

### NL2SQL（v3 混合多智能体）

```
用户输入 → Planner(任务计划) → SQL Specialist(工具探索 → submit_sql)
  → Validate Gate(只读安全 + 方言 + Schema)
  → 失败则返回结构化错误并定向修复 → Execute Gate(沙箱) → AG-UI SSE 响应
```

### 知识问答

```
用户输入 → Planner(知识任务) → Knowledge Pipeline
  → HybridKnowledgeRetriever(精确ripgrep+语义Qdrant+RRF融合)
  → LiteLLM 生成回答 → AG-UI SSE 响应
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
- 163 个后端测试，覆盖 agents / API / validator / sandbox / crypto

## 安全边界

- SQL 执行只允许只读查询（`SQLSandbox` AST + 字符串双重校验）
- 生产必须配套数据库账号层只读权限 + SQL 执行审计
- `.env` 不得提交，`.env.example` 只能使用假值
