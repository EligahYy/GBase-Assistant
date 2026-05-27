# GBase 8a Agent 数据库助手 — Codex 项目指南

> 本文件是项目的统一入口文档，面向 Codex / AI 编码 Agent / 新加入开发者。
> 架构设计、开发规范、关键文件、运行命令和当前风险都以本文为准；阶段计划见 `docs/ROADMAP.md`。

---

## 1. 项目定位

**GBase 8a Agent 数据库助手** 是一个面向内部产品、研发、测试团队的中文 AI 数据库助手。

核心能力：

- 用户用中文自然语言提问，系统生成兼容 GBase 8a MPP 数据库的 SQL。
- 系统回答 GBase 8a 方言、错误码、运维、性能调优等知识问题。
- 已提前落地只读 SQL 执行、结果表格化、数据浏览器和性能洞察。

当前阶段：

- Phase 1 / 2 / 3 已完成。
- Phase 5 SQL 执行能力已提前落地。
- 当前处于 **Phase 3.5 文档与稳态加固 + Phase 4 上线前准备**。
- 项目状态是 Demo 完成态，下一目标是生产化加固。

目标用户与部署：

- 用户规模：内部团队，预计 <50 人。
- 部署方式：单机部署，前后端分离，Qdrant Docker。
- 主要语言：中文。文档、注释、UI、Prompt 优先中文。

---

## 2. 技术栈

### 后端

| 层 | 技术 |
|---|---|
| 运行时 | Python 3.12+ |
| Web 框架 | FastAPI 0.115+ |
| ORM | SQLAlchemy 2.0 async + aiosqlite |
| 迁移 | Alembic |
| LLM | LiteLLM，多模型 fallback |
| SQL 解析 | sqlglot，自定义 GBase 8a 方言 |
| 向量库 | Qdrant |
| Embedding | 默认 LiteLLM + 阿里云 `text-embedding-v4`，备选本地 `BAAI/bge-m3` |
| 配置 | Pydantic Settings + `backend/config/models.yaml` |
| 测试 | pytest + pytest-asyncio |
| 质量 | ruff |

### 前端

| 层 | 技术 |
|---|---|
| 框架 | Vue 3.5+ |
| 类型 | TypeScript |
| UI | Naive UI |
| 状态 | Pinia Setup Store |
| 路由 | Vue Router |
| 构建 | Vite |
| HTTP | Axios + fetch SSE |

### 数据层

- 应用数据库：SQLite，`sqlite+aiosqlite`，为单机零运维优先。
- 向量数据库：Qdrant，本地默认 `http://localhost:6333`。
- 知识库源：项目根目录 `knowledge/` 下的 YAML / JSON / JSONL 文件。
- 生产数据库连接：GBase 8a / MySQL 协议原生连接，密码 Fernet 加密存储。

---

## 3. 顶层结构

```text
gbase8a-assistant/
├── AGENTS.md                  # 统一项目指南与架构入口
├── ARCHITECTURE.md            # 兼容旧链接的过渡页，指向 AGENTS.md
├── README.md                  # 用户/项目简介
├── Makefile                   # 常用命令
├── backend/                   # FastAPI 后端
├── frontend/                  # Vue 前端
├── knowledge/                 # 方言规则、Few-shot、FAQ、错误码、运维文档
├── docs/
│   ├── ROADMAP.md             # 当前下一步计划
│   ├── demo-cases.md          # 演示/评测用例
│   └── design/                # 前端设计方案
└── deploy/                    # Docker Compose / Nginx / 镜像配置
```

`.claude/` 不是项目运行依赖；如再次出现，应视为本地工具缓存或旧 worktree，不作为项目文档源。

---

## 4. 系统架构

当前真实架构：

```text
Vue SPA
  ├─ Chat / Settings / ErrorCode / SqlEditor / DataBrowser / Insights
  │
  └─ HTTP + SSE
        │
FastAPI
  ├─ Chat orchestration
  ├─ Text-to-SQL chain
  ├─ QA / RAG chain
  ├─ SQL validator + sandbox
  ├─ Connection / Schema / Admin / Insights APIs
  │
  ├─ SQLite       对话、消息、连接、反馈、摘要预埋
  ├─ Qdrant       Schema / Example / Knowledge 向量检索
  ├─ LiteLLM      Intent / SQL generation / Knowledge QA
  └─ GBase 8a     只读查询执行、Schema 同步、性能洞察
```

设计原则：

- **MVP 优先**：每个阶段都要有可演示闭环。
- **Protocol 驱动**：核心能力依赖 `backend/app/protocols.py`，实现通过依赖注入替换。
- **渐进复杂度**：先函数链，只有出现复杂状态、checkpoint、人工审批时才评估 LangGraph。
- **知识库文件为源**：Qdrant 是索引与检索层，`knowledge/` 文件仍是可审计源。
- **安全优先**：SQL 执行只能作为只读能力；生产必须配套数据库账号层只读权限。

---

## 5. 后端模块地图

```text
backend/app/
├── main.py              # FastAPI app factory + lifespan，初始化 DB / Qdrant / embedding
├── config.py            # Settings，读取 .env 与 models.yaml
├── database.py          # async SQLAlchemy engine/session
├── protocols.py         # 核心接口与数据结构
├── dependencies.py      # Protocol 绑定与 Qdrant 自动降级
├── api/
│   ├── chat.py          # 聊天 HTTP 入参/出参与服务层绑定
│   ├── connections.py   # 连接 CRUD、状态、Schema 浏览、SQL 查询
│   ├── tools.py         # 错误码查询
│   ├── admin.py         # reindex、feedback enrich 等管理接口
│   ├── insights.py      # 性能洞察 API
│   ├── models.py        # 模型列表
│   └── health.py        # 依赖健康检查
├── chains/
│   ├── intent.py        # 意图分类：sql / qa / general
│   ├── sql_chain.py     # NL → SQL → 验证 → 自纠错
│   └── qa_chain.py      # 知识问答 RAG
├── services/
│   ├── chat_service.py          # 聊天请求编排
│   ├── conversation_service.py  # 对话上下文、消息持久化、反馈
│   ├── sql_execution_service.py # 聊天链路 SQL 执行
│   └── summary_service.py       # 对话摘要后台任务
├── llm/
│   ├── client.py        # LiteLLM 封装 + fallback + metrics
│   └── prompts.py       # Prompt 模板
├── sql/
│   ├── dialect.py       # GBase 8a sqlglot 方言
│   ├── validator.py     # SQL 语法、方言、Schema 交叉引用验证
│   └── sandbox.py       # 只读执行沙箱
├── vector/
│   ├── client.py        # Qdrant manager
│   ├── embedder.py      # Embedder 工厂
│   ├── embedders/       # LiteLLM / local embedding 实现
│   ├── retrievers.py    # Qdrant retriever
│   └── ingest.py        # 知识库与 Schema 入库
├── db_connectors/       # GBase 8a / MySQL 协议连接器
├── security/crypto.py   # Fernet 密码加密
├── jobs/                # 摘要、反馈 enrich 任务
├── observability/       # 进程内 metrics
├── models/              # SQLAlchemy ORM
└── schemas/             # Pydantic schema
```

后端分层约束：

```text
API 路由 (api/*.py)
  → 服务层 (services/*.py)
  → 业务链 (chains/*.py)
  → 工具层 (sql/, llm/, knowledge/, vector/, db_connectors/)
  → 数据层 (models/, database.py)
```

聊天链路已经完成第一轮边界收敛：`api/chat.py` 保持 HTTP 层职责，聊天编排移入 `services/chat_service.py`。

---

## 6. 前端模块地图

```text
frontend/src/
├── main.ts
├── App.vue
├── router/index.ts
├── api/
│   ├── client.ts
│   ├── chat.ts
│   ├── connections.ts
│   ├── models.ts
│   ├── tools.ts
│   ├── admin.ts
│   └── feedback.ts
├── stores/
│   ├── chat.ts
│   └── connection.ts
├── components/
│   ├── chat/
│   │   ├── ChatPanel.vue
│   │   ├── MessageBubble.vue
│   │   └── SqlBlock.vue
│   └── layout/Sidebar.vue
├── composables/
│   ├── useSSE.ts
│   ├── useContentParser.ts
│   ├── useSavedQueries.ts
│   └── useTheme.ts
└── views/
    ├── HomeView.vue
    ├── SettingsView.vue
    ├── ErrorCodeView.vue
    ├── SqlEditorView.vue
    ├── DataBrowserView.vue
    └── InsightsView.vue
```

当前前端主要架构债：`SettingsView.vue`、`DataBrowserView.vue`、`SqlEditorView.vue`、`InsightsView.vue`、`Sidebar.vue` 单文件偏大，Phase 4.5 需要拆分组件与 composable。

---

## 7. 核心链路

### 7.1 Text-to-SQL

```text
用户中文问题
  → intent.classify_intent()
  → SchemaRetriever 检索相关表
  → ExampleRetriever 检索 Few-shot
  → dialect_rules 注入 Prompt
  → LiteLLM 生成 SQL
  → extract_sql_from_markdown()
  → validate_sql()
  → 失败则纠错重试，最多 3 次
  → 返回 SQL + 中文解释
  → 如绑定真实连接且验证通过，可走 SQLSandbox 只读执行
```

### 7.2 知识问答 / RAG

```text
用户问题
  → KnowledgeRetriever
  → Qdrant 语义检索
  → 空结果或异常回退文件关键词匹配
  → LiteLLM 基于 context 回答
  → MessageBubble 展示 sources
```

### 7.3 向量检索降级

```text
应用启动
  → Qdrant ensure_collections
  → embedding warmup
  → 后台 sync_all_to_qdrant

请求处理
  → dependencies.get_*_retriever()
  → Qdrant 可用：primary retriever
  → primary 空结果或异常：fallback retriever
  → chain 层无感知
```

### 7.4 SSE 流式输出

- 接口：`POST /api/chat/stream`
- 格式：`data: {"type": "...", "content": "..."}\n\n`
- 常见 type：`text`、`sql`、`warning`、`sources`、`result`、`result_error`、`message_ids`、`done`、`error`
- 前端入口：`frontend/src/composables/useSSE.ts`

---

## 8. 运行命令

优先使用根目录 `Makefile`。

```bash
# 安装依赖
make install

# 启动后端 http://localhost:8000
make dev-backend

# 启动前端 http://localhost:5173
make dev-frontend

# 后端测试
cd backend && TESTING=1 uv run pytest -v

# 或使用 Makefile 当前测试命令
make test

# 代码检查
make lint

# 数据库迁移
make migrate
make migration msg="add xxx table"
```

Qdrant 开发：

```bash
cd deploy && docker compose up -d qdrant
```

开发时可不启动 Qdrant；后端会自动降级。测试请使用 `TESTING=1` 跳过 Qdrant / Embedding 初始化。

---

## 9. 环境变量

复制 `.env.example` 为 `backend/.env`，至少配置一个 LLM API Key。

关键变量：

```bash
DATABASE_URL=sqlite+aiosqlite:///./data/app.db
DEFAULT_MODEL=deepseek/deepseek-chat
CORS_ORIGINS=["http://localhost:5173"]
DEBUG=true

DEEPSEEK_API_KEY=sk-xxx
DASHSCOPE_API_KEY=sk-xxx
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-xxx

QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
ADMIN_TOKEN=
SKIP_VECTOR_SYNC=
TESTING=
```

`.env` 不得提交。`.env.example` 只能使用假值。

---

## 10. 编码规范

### Python

- 公共函数必须有类型注解。
- FastAPI 路由、数据库操作、LLM 调用必须 async/await。
- SQLAlchemy 使用 async session，禁止同步 session。
- LLM 调用统一经过 `LiteLLMClientImpl` / `LLMClient` Protocol。
- ruff：行宽 120、双引号、导入排序。
- JSON 兼容 SQLite → PostgreSQL 迁移：用 `Text` + `json.dumps/loads`，不要使用 JSONB/ARRAY。
- UUID 用 `String(36)` 和 `str(uuid.uuid4())`。

### Vue / TypeScript

- 组件必须使用 `<script setup lang="ts">`。
- Props 使用 `defineProps<{...}>()`。
- Emits 使用 `defineEmits<{...}>()`。
- Pinia 使用 Setup Store。
- API 调用集中在 `frontend/src/api/`。
- 样式优先 Naive UI；自定义样式使用 scoped style 和 CSS 变量。
- 禁止引入 Tailwind 或新的 CSS 框架，除非明确重构设计系统。

---

## 11. 测试约定

当前测试口径：后端 pytest 约 80 个用例，覆盖 SQL validator、SQL chain、API、依赖降级、crypto、sandbox、metrics。

约定：

- 单元测试必须 Mock 外部 LLM API。
- 涉及 Qdrant / Embedding 的测试使用 `TESTING=1` 走降级路径。
- 真实 LLM 或真实 GBase 连接测试需标记 integration，不进入默认快速测试。
- 前端尚未建立 Vitest + Vue Test Utils，这是 Phase 4.5 任务。

---

## 12. 安全边界

必须牢记：

- 当前系统已经支持 SQL 执行，不再是“只生成 SQL”。
- SQL 执行只允许只读查询，经过 `SQLSandbox` 的 AST 校验、多语句拦截、超时和行数限制。
- 解析器级沙箱不是最终安全边界；生产必须配套数据库账号层只读权限。
- 生产上线前必须补齐：
  - 用户认证与限流
  - SQL 执行审计日志
  - 凭证操作审计
  - CORS 收窄
  - HTTPS 与安全 Header
  - 加密密钥管理或轮换策略

---

## 13. 关键文件速查

| 想做什么 | 先看 |
|---|---|
| 当前计划 | `docs/ROADMAP.md` |
| 演示用例 | `docs/demo-cases.md` |
| 后端入口 | `backend/app/main.py` |
| 路由注册 | `backend/app/api/router.py` |
| 聊天接口 | `backend/app/api/chat.py` |
| SQL 生成 | `backend/app/chains/sql_chain.py` |
| 知识问答 | `backend/app/chains/qa_chain.py` |
| 意图分类 | `backend/app/chains/intent.py` |
| Prompt | `backend/app/llm/prompts.py` |
| LLM 客户端 | `backend/app/llm/client.py` |
| Protocol | `backend/app/protocols.py` |
| 依赖注入 / 降级 | `backend/app/dependencies.py` |
| SQL 验证 | `backend/app/sql/validator.py` |
| SQL 沙箱 | `backend/app/sql/sandbox.py` |
| 数据库连接器 | `backend/app/db_connectors/` |
| 凭证加密 | `backend/app/security/crypto.py` |
| 向量检索 | `backend/app/vector/` |
| 指标埋点 | `backend/app/observability/` |
| ORM 模型 | `backend/app/models/` |
| Pydantic schema | `backend/app/schemas/` |
| 前端聊天 | `frontend/src/components/chat/` |
| 前端 API | `frontend/src/api/` |
| 前端路由 | `frontend/src/router/index.ts` |
| 前端视图 | `frontend/src/views/` |
| 方言规则 | `knowledge/dialect_rules/` |
| Few-shot 示例 | `knowledge/examples/sql_examples.jsonl` |
| FAQ / 错误码 / 运维 | `knowledge/docs/` |

---

## 14. 当前架构改进队列

优先级从高到低：

1. **文档收敛**：本文作为唯一基础架构入口；`ROADMAP.md` 只放下一步计划。
2. **补 `/metrics`**：已有进程内 metrics，缺 Prometheus 文本渲染与路由。
3. **继续边界收敛**：优先拆分 `connections.py` 与 `insights.py` 中的业务逻辑。
4. **补审计与认证**：SQL 执行流水、凭证操作日志、JWT/Session、限流。
5. **前端拆分**：大型 view 拆 panel/table/composable，引入最小组件测试。
6. **E2E 验证**：基于 `docs/demo-cases.md` 建 Playwright 冒烟测试。

---

## 15. Codex 工作约定

- 先读本文，再读 `docs/ROADMAP.md`。
- 不再以 `.claude/` 或旧 worktree 中的文档为准。
- 修改文档时优先保持 `AGENTS.md`、`ROADMAP.md`、`README.md` 三者一致。
- 修改架构时同步更新本文的模块地图和改进队列。
- 不要回滚用户已有改动；工作区可能存在未提交变更。
- 对 SQL 执行、凭证、认证、外部连接相关改动，必须同时考虑测试和安全边界。
