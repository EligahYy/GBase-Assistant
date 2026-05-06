# GBase 8a Agent 数据库助手 — AGENTS.md

> 本文件面向 AI 编码 Agent。如果你正在阅读此文件，说明你对该项目一无所知。以下信息均基于项目实际代码和配置，而非假设。

---

## 项目概述

**GBase 8a Agent 数据库助手** 是一个面向内部团队的 AI 数据库助手。用户通过自然语言中文对话，系统生成兼容国产 GBase 8a MPP 数据库的 SQL 查询，或回答 GBase 8a 相关的技术问题。

- **当前阶段**：Phase 3 Sprint 1 已完成，Sprint 2 进行中（向量检索核心已落地：Qdrant + Embedder 工厂 + 三个 retriever + 自动降级回退；待办：错误码工具、RAG 完整接入、管理接口）
- **目标用户**：<50 人的内部产品/研发/测试团队
- **部署方式**：单机部署，前后端分离 + Qdrant Docker
- **主要语言**：中文（文档、注释、UI、Prompt 均以中文为主）

> 详细的 Phase 3 任务清单与 Sprint 排期见 [`docs/ROADMAP.md`](docs/ROADMAP.md)。

---

## 技术栈

### 后端

| 技术 | 版本/说明 | 用途 |
|------|----------|------|
| Python | 3.12+ | 运行时 |
| FastAPI | 0.115+ | Web 框架 |
| SQLAlchemy | 2.0+ (async) | ORM |
| aiosqlite | — | SQLite 异步驱动 |
| Alembic | — | 数据库迁移 |
| LiteLLM | 1.83+ | 统一 LLM 调用接口 |
| sqlglot | 30.4+ | SQL 解析与方言验证 |
| Pydantic | v2 | 数据校验与配置管理 |
| uv | — | Python 包管理与虚拟环境 |
| ruff | — | 代码格式化和 Lint |
| pytest / pytest-asyncio | — | 测试框架 |

### 前端

| 技术 | 版本/说明 | 用途 |
|------|----------|------|
| Vue | 3.5+ | 框架 |
| TypeScript | 5.x / ~6.0 | 类型系统 |
| Naive UI | 2.44+ | 组件库 |
| Pinia | 3.0+ | 状态管理 |
| Vue Router | 5.0+ | 路由 |
| Vite | 6.x / 8.x | 构建工具 |
| Axios | 1.15+ | HTTP 客户端 |

### 数据层

- **应用数据库**：SQLite（`sqlite+aiosqlite`），零运维，单文件存储
- **向量数据库**：Qdrant（Docker 部署，本地默认 `http://localhost:6333`）— Phase 3 Sprint 1 已接入，Schema/Few-shot/Knowledge 检索均支持向量化 + 自动降级
- **Embedding**：默认 LiteLLM + 阿里云 `text-embedding-v4`（dim=1024），可在 `models.yaml` 切换为本地 `BAAI/bge-m3`
- **知识库**：文件驱动（`knowledge/` 目录下的 YAML/JSONL/JSON），通过 `ingest.py` 同步到 Qdrant

---

## 项目结构

```
gbase8a-assistant/
├── AGENTS.md                  # 本文件
├── ARCHITECTURE.md            # 架构设计文档（含 Phase 演进规划）
├── CLAUDE.md                  # 详细开发规范与编码约束
├── Makefile                   # 常用命令入口
├── .env.example               # 环境变量模板
│
├── docs/                      # 项目文档
│   ├── ROADMAP.md             # Phase 3 路线图与 Sprint 任务清单
│   └── design/
│       └── redesign-proposal.md   # 前端 redesign 设计方案
│
├── backend/                   # FastAPI 后端
│   ├── pyproject.toml         # uv 项目配置、依赖、ruff 配置、pytest 配置
│   ├── uv.lock                # uv 锁定文件
│   ├── app/
│   │   ├── main.py            # FastAPI 应用工厂 + lifespan（含 Qdrant 初始化）
│   │   ├── config.py          # Pydantic Settings，读取 .env + models.yaml
│   │   ├── database.py        # SQLite async engine + session factory
│   │   ├── protocols.py       # 核心接口定义（SchemaRetriever/Embedder/LLMClient 等 Protocol）
│   │   ├── dependencies.py    # FastAPI 依赖注入（Phase 3 已带 Qdrant 自动降级）
│   │   ├── api/
│   │   │   ├── router.py      # 路由注册
│   │   │   ├── chat.py        # 聊天 API（POST /chat, POST /chat/stream, 对话 CRUD）
│   │   │   ├── connections.py # 数据库连接管理 CRUD（保存时自动后台 Schema 向量化）
│   │   │   ├── models.py      # 模型列表 API（读 models.yaml）
│   │   │   └── health.py      # 健康检查
│   │   ├── chains/
│   │   │   ├── sql_chain.py   # Text-to-SQL 生成链（含自纠错重试）
│   │   │   ├── qa_chain.py    # 知识问答链
│   │   │   └── intent.py      # 意图分类（sql / qa / general）
│   │   ├── sql/
│   │   │   ├── dialect.py     # sqlglot GBase8A 方言定义
│   │   │   └── validator.py   # SQL 语法 + 方言合规 + Schema 交叉引用验证
│   │   ├── llm/
│   │   │   ├── client.py      # LiteLLM 封装（complete/stream，多模型 fallback）
│   │   │   └── prompts.py     # Prompt 模板管理
│   │   ├── knowledge/
│   │   │   └── loader.py      # 文件驱动 retriever（DbSchemaRetriever / FileExampleRetriever / FileKnowledgeRetriever）
│   │   ├── vector/            # Phase 3 — 向量检索模块
│   │   │   ├── client.py      # Qdrant async client + collections 生命周期
│   │   │   ├── embedder.py    # Embedder 工厂（local bge-m3 / LiteLLM 远程）
│   │   │   ├── embedders/     # Embedder 实现：local.py + litellm.py
│   │   │   ├── retrievers.py  # Qdrant Schema/Example/Knowledge Retriever
│   │   │   └── ingest.py      # FAQ / SQL 示例 / 错误码 / Schema 向量化入库
│   │   ├── models/
│   │   │   ├── connection.py  # DbConnection ORM
│   │   │   ├── conversation.py# Conversation ORM（含 archived/tags）
│   │   │   ├── message.py     # Message ORM（token_usage 用 Text 存 JSON）
│   │   │   ├── sql_feedback.py        # SQL 反馈 ORM
│   │   │   ├── conversation_summary.py # 对话摘要 ORM（Phase 4 预埋）
│   │   │   └── user_pattern.py        # 用户查询模式 ORM（Phase 4 预埋）
│   │   └── schemas/
│   │       ├── chat.py        # ChatRequest/ChatResponse/MessageResponse Pydantic schema
│   │       └── connection.py  # ConnectionCreate/Update/Response schema
│   ├── config/
│   │   └── models.yaml        # LLM + Embedding + Qdrant collections 配置（已深度接入 LiteLLMClientImpl）
│   ├── alembic/               # 数据库迁移（当前 2 个迁移：archived_tags、conversation_summary/user_pattern）
│   └── tests/                 # pytest 测试套件（60 测试通过）
│       ├── test_api.py        # API 集成测试
│       ├── test_dependencies.py # Phase 3 降级路径测试（9 个用例）
│       ├── test_sql_chain.py  # SQL 生成链路测试（Mock LLM）
│       └── test_sql_validator.py # SQL 验证测试
│
├── frontend/                  # Vue 3 前端
│   ├── package.json           # npm 配置，Node 引擎要求 ^20.19.0 || >=22.12.0
│   ├── vite.config.ts         # Vite 配置（含 @ -> src 别名）
│   ├── tsconfig*.json         # TypeScript 配置
│   ├── src/
│   │   ├── main.ts            # 应用入口：Pinia + Router + Naive UI
│   │   ├── App.vue            # 根组件（含 sidebar 开关逻辑、主题切换、全局 CSS 变量）
│   │   ├── router/index.ts    # 路由定义（HomeView + SettingsView）
│   │   ├── stores/
│   │   │   ├── chat.ts        # 对话状态管理（消息列表、流式消息处理）
│   │   │   └── connection.ts  # 数据库连接状态
│   │   ├── api/
│   │   │   ├── client.ts      # Axios 实例（baseURL: localhost:8000/api）
│   │   │   ├── chat.ts        # 聊天 API 封装（含 SSE stream）
│   │   │   ├── connections.ts # 连接管理 API 封装
│   │   │   ├── models.ts      # 模型列表 API
│   │   │   └── feedback.ts    # SQL 反馈 API
│   │   ├── components/
│   │   │   ├── chat/
│   │   │   │   ├── ChatPanel.vue       # 聊天主面板（输入、消息列表、空状态提示）
│   │   │   │   ├── MessageBubble.vue   # 单条消息气泡（含流式光标）
│   │   │   │   └── SqlBlock.vue        # SQL 代码块展示 + 复制按钮
│   │   │   └── layout/
│   │   │       └── Sidebar.vue         # 对话历史侧栏（新建/重命名/归档/标签/删除）
│   │   ├── views/
│   │   │   ├── HomeView.vue   # 首页（仅挂载 ChatPanel）
│   │   │   └── SettingsView.vue # 设置页（模型选择 + 连接管理）
│   │   └── composables/
│   │       ├── useSSE.ts      # SSE 流式请求封装（含 token 缓冲优化）
│   │       ├── useContentParser.ts  # 实时解析 ```sql...``` 代码块
│   │       └── useTheme.ts    # 暗色/亮色主题切换
│   └── public/                # 静态资源
│
├── knowledge/                 # GBase 8a 知识库（文件驱动 + Qdrant 同步源）
│   ├── dialect_rules/
│   │   ├── unsupported_features.yaml  # 不支持的特性清单
│   │   ├── syntax_differences.yaml    # 语法差异与示例
│   │   └── function_mapping.yaml      # 函数兼容性映射
│   ├── examples/
│   │   └── sql_examples.jsonl         # Few-shot NL→SQL 示例（30 条，含 GBase 特有语法）
│   └── docs/
│       ├── faq.json                   # FAQ 知识库（38 条 JSON 数组）
│       └── error_codes.json           # ⚠️ Sprint 2 待补：GBase 8a 错误码知识库
│
└── deploy/                    # 部署配置
    ├── docker-compose.yml     # backend + frontend + qdrant + nginx 全链路编排
    ├── Dockerfile.backend     # 后端镜像
    ├── Dockerfile.frontend    # 前端镜像
    └── nginx.conf             # 反向代理配置
```

---

## 构建和运行命令

所有常用命令已封装在根目录的 `Makefile` 中：

```bash
# 安装依赖（后端 uv sync + 前端 npm install）
make install

# 启动后端开发服务器（http://localhost:8000，含自动重载）
make dev-backend

# 启动前端开发服务器（http://localhost:5173）
make dev-frontend

# 运行后端测试（pytest）
make test

# 代码检查（后端 ruff + 前端 eslint）
make lint

# 数据库迁移（创建表，当前用 init_db 自动创建， Alembic 备用）
make migrate

# 创建新的 Alembic 迁移脚本
make migration msg="add xxx table"
```

### 手动启动

```bash
# 后端
cd backend
uv run uvicorn app.main:app --reload --host 0.0.0.0 --port 8000

# 前端
cd frontend
npm run dev
```

### 环境变量

复制 `.env.example` 为 `backend/.env`，至少配置一个 LLM API Key 和（如启用向量检索）Qdrant 地址：

```bash
DEEPSEEK_API_KEY=sk-xxx
DASHSCOPE_API_KEY=sk-xxx
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-xxx

DATABASE_URL=sqlite+aiosqlite:///./data/app.db
DEFAULT_MODEL=deepseek/deepseek-chat
CORS_ORIGINS=["http://localhost:5173"]
DEBUG=true

# Phase 3 — 向量检索
QDRANT_URL=http://localhost:6333
QDRANT_API_KEY=
```

> Qdrant 不可用时后端会自动降级到文件/全量模式，开发阶段可以不启动。生产部署需 `cd deploy && docker compose up -d qdrant`。

---

## 代码风格规范

### 后端 Python

- **格式化**：ruff，行宽 `120`，引号双引号
- **类型注解**：所有公共函数必须有类型注解
- **异步规范**：所有数据库操作、LLM 调用、FastAPI 路由必须写 `async/await`
  - SQLAlchemy 用 `async_session`，禁止同步 session
  - LLM 调用用 `litellm.acompletion()`
  - FastAPI 路由一律 `async def`
- **分层架构**（严格遵循）：
  ```
  API 路由 (api/*.py) → 业务链 (chains/*.py) → 工具层 (sql/, llm/, knowledge/) → 数据层 (models/, database.py)
  ```
  - API 层只做参数校验和调用 chain，不写业务逻辑
  - chain 层写核心逻辑，必须是“纯函数”语义（输入 `message + context`，输出 `result`，不操作全局状态）
  - 所有 chain 的依赖必须通过参数注入 Protocol 实例，禁止在函数内部硬编码构造依赖
- **数据库兼容性**（为 SQLite → PostgreSQL 迁移预留）：
  - UUID 用 `String(36)` 存储，Python 端 `str(uuid.uuid4())`
  - JSON 数据用 `Text` 存储 + `json.dumps/loads`，禁止用 `JSONB` 或 `ARRAY`
  - Alembic 已配置 `render_as_batch=True`（SQLite 不支持 `ALTER TABLE DROP COLUMN`）

### 前端 Vue / TypeScript

- **组件语法**：必须使用 `<script setup lang="ts">`
- **Props/Emits**：
  - Props: `defineProps<{...}>()` 泛型写法
  - Emits: `defineEmits<{...}>()`
- **状态管理**：Pinia 使用 Setup Store 语法（`defineStore('name', () => { ... })`）
- **API 调用**：全部集中在 `src/api/` 目录，返回类型必须定义 TypeScript interface
- **样式**：
  - 优先使用 Naive UI 自带样式
  - 自定义样式用 `<style scoped>` + CSS 变量（已定义在 `App.vue` 的 `:root`）
  - **禁止引入 Tailwind 或其他 CSS 框架**

---

## 测试说明

**当前状态：60 个 pytest 用例全部通过。**

- `backend/tests/test_sql_validator.py`(29) — SQL 方言验证测试
- `backend/tests/test_sql_chain.py`(9) — SQL 生成链路测试（Mock LLM）
- `backend/tests/test_api.py`(13) — API 集成测试
- `backend/tests/test_dependencies.py`(9) — Phase 3 自动降级路径测试

### 测试运行方式

```bash
cd backend && TESTING=1 uv run pytest -v
```

`TESTING=1` 环境变量会跳过 Qdrant/Embedding 模型加载（使用 `_FakeEmbedder`），让单元测试不依赖外部服务。

pytest 配置已写在 `pyproject.toml` 中：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

如果你需要添加测试，请遵循以下约定：
- 单元测试必须 Mock 外部 LLM API 调用（不依赖真实网络）
- 集成测试如需真实 LLM，标记 `@pytest.mark.integration`
- 涉及 Qdrant 的测试请通过 `TESTING=1` 让 retriever 走降级路径

---

## 核心架构模式

### Protocol 驱动设计（最重要的约束）

`backend/app/protocols.py` 定义了所有核心抽象接口：

- `SchemaRetriever` — Schema 检索（Phase 3 已支持向量化）
- `ExampleRetriever` — Few-shot 示例检索（Phase 3 已支持向量化）
- `KnowledgeRetriever` — 知识库检索（Phase 3 已支持 RAG）
- `LLMClient` — LLM 调用（`complete` + `stream`，多模型 fallback）
- `Embedder` — 文本向量化（Phase 3 新增；本地 bge-m3 / 远程 LiteLLM 双实现）
- `ChatChain` — 对话链抽象

**规则**：
- 所有 chain 函数必须通过参数接收 Protocol 实例
- `dependencies.py` 负责将 Protocol 绑定到具体实现，并自动处理 Qdrant 不可用时的降级回退
- 后续升级（如引入 LangGraph）时，**只改 `dependencies.py`，不改调用方代码**

### Intent 分类 + Chain 路由

用户消息首先经过 `intent.classify_intent()` 判断意图：
- `"sql"` → `sql_chain.run_sql_chain()` / `stream_sql_chain()`
- `"qa"` → `qa_chain.run_qa_chain()` / `stream_qa_chain()`
- `"general"` → 直接调用 LLM 通用回复

### SQL 生成与验证流程

```
用户输入
  → 加载方言规则（YAML）
  → Schema 检索（Phase 3：Qdrant 向量检索 → 失败回退全量 DDL）
  → Few-shot 检索（Phase 3：Qdrant 动态检索 → 失败回退文件前 5 条）
  → LLM 生成 SQL（temperature=0.1）
  → sqlglot 语法解析 + GBase 8a 方言合规检查 + Schema 交叉引用
  → 若验证失败且重试次数 < 3，追加纠错 prompt 重新生成
  → 返回 SQL + 中文解释
```

### Phase 3 — 向量检索调用链

```
应用启动 (lifespan)
  → Qdrant 健康检查 → 失败时 set_qdrant_available(False)
  → Embedding 模型预热（warmup）
  → sync_all_to_qdrant：FAQ / SQL examples / 错误码 增量同步（按文件 hash）

请求处理
  → dependencies.get_xxx_retriever()
    → is_qdrant_available()？
      ✅ 是 → QdrantXxxRetriever（向量检索） → 命中则返回
      ❌ 否（或检索结果为空）→ 回退到 File/Db Retriever
  → chain 不感知降级，调用代码无变化
```

### SSE 流式输出

- 接口：`POST /api/chat/stream`
- 数据格式：`data: {"type": "text|sql|warning|done|error", "content": "..."}\n\n`
- 前端通过 `useSSE.ts` 中的 `fetch + ReadableStream` 接收并逐 token 渲染
- 流结束后，后端自动将完整消息持久化到 SQLite

---

## 安全注意事项

1. **API Keys 管理**：`.env.example` 中曾出现真实 API Key（已记录在文件历史中）。当前 `.env` 文件在 `.gitignore` 中，**务必确保 `.env` 不会被提交到 Git**。如果新增环境变量模板，请使用假值 `sk-xxx`。

2. **SQL 安全**：
   - 系统目前 **只生成 SQL，不执行 SQL**（无数据库直连执行功能）
   - `validator.py` 会对 DML（INSERT/UPDATE/DELETE）和 DROP 输出安全警告
   - 所有生成的 SQL 都需要用户人工确认后再使用

3. **CORS**：后端 CORS 已配置为允许 `localhost:5173` 等开发地址。生产部署时必须收窄 `CORS_ORIGINS`。

4. **输入输出**：FastAPI 依赖 Pydantic 做请求校验，暂无额外的 SQL 注入或 XSS 风险（因为不执行用户 SQL）。

---

## 关键文件速查

| 想做什么 | 先看这个文件 |
|---------|------------|
| 了解整体架构设计 | `ARCHITECTURE.md` |
| 看 Phase 3 任务清单 | `docs/ROADMAP.md` |
| 了解编码规范 | `CLAUDE.md` |
| 改 API 接口 | `backend/app/api/chat.py` |
| 改 SQL 生成逻辑 | `backend/app/chains/sql_chain.py` |
| 改 Prompt 模板 | `backend/app/llm/prompts.py` |
| 改 SQL 验证规则 | `backend/app/sql/validator.py` + `knowledge/dialect_rules/*.yaml` |
| 改 Schema/Example/Knowledge 检索 | `backend/app/dependencies.py` + `backend/app/vector/retrievers.py` |
| 改 Embedding 实现 | `backend/app/vector/embedder.py` + `backend/app/vector/embedders/` |
| 调整向量入库逻辑 | `backend/app/vector/ingest.py` |
| 改前端聊天界面 | `frontend/src/components/chat/ChatPanel.vue` |
| 改流式接收逻辑 | `frontend/src/composables/useSSE.ts` |
| 改数据库模型 | `backend/app/models/*.py` |
| 添加 Few-shot 示例 | `knowledge/examples/sql_examples.jsonl` |
| 添加 FAQ 知识 | `knowledge/docs/faq.json` |
| 添加错误码（待补） | `knowledge/docs/error_codes.json`（Sprint 2） |

---

## 已知短板与下一步（供 Agent 参考）

> 本节为高频变化区，详细 Sprint 任务请以 [`docs/ROADMAP.md`](docs/ROADMAP.md) 为准。

### 已解决的问题（Phase 2 → Phase 3 Sprint 1）
- ~~测试缺失~~：60 个 pytest 用例全部通过（含 9 个 Phase 3 降级路径测试）
- ~~模型配置未完全接入~~：`LiteLLMClientImpl` 已深度接入 `models.yaml`（intent/sql_generation/knowledge_qa）
- ~~前端路由极简~~：已新增 `/settings`，支持模型选择 + 连接管理
- ~~Alembic 迁移脚本为空~~：当前 2 个迁移（archived_tags、conversation_summary/user_pattern）
- ~~部署目录为空~~：`deploy/` 已补齐 Dockerfile + docker-compose + nginx
- ~~FAQ 知识库单薄~~：已扩展至 38 条
- ~~Schema/Few-shot/Knowledge 检索全量注入~~：Phase 3 Sprint 1 已接入 Qdrant 向量检索 + 自动降级

### 进行中（Phase 3 Sprint 2 — RAG + 错误码工具）
1. **错误码知识库**：`knowledge/docs/error_codes.json` 缺失，需准备 50+ 条
2. **错误码查询接口**：`POST /api/tools/error-code` 待实现
3. **管理接口**：`POST /api/admin/reindex` 强制全量重建待实现
4. **运维文档分块**：性能/参数/集群相关 `knowledge/docs/ops_*.json` 待补
5. **Settings 状态卡**：前端 Qdrant 状态指示 + Reindex 按钮
6. **MessageBubble sources 区**：RAG 引用来源展示

### 即将处理（阶段 A.2 重构，与 Sprint 2 并行）
1. **Fallback wrapper 抽象**：`dependencies.py` 三个降级类合并为泛型 `FallbackRetriever[T]`
2. **Embedding 维度配置化**：`models.yaml` 显式声明，去掉 `litellm.py` 硬编码判断
3. **Lifespan 异步化**：`main.py` 中 `sync_all_to_qdrant` 改为 `asyncio.create_task` + `SKIP_VECTOR_SYNC` env 开关

### 上线前必做（Phase 3 Sprint 4，本期 Demo 阶段降权）
- GitHub Actions CI（lint → test → build → docker build）
- `/metrics` Prometheus 端点
- LangGraph 评估文档（预判：不引入）
- 性能基准测试（向量检索 vs 全量注入）
- SQL 反馈闭环 → 自动 enrich Few-shot 库
- Vitest + Vue Test Utils 配置

### Phase 4 预备项
- 长期记忆：复用 `ConversationSummary` / `UserPattern` 模型
- SQL 执行沙箱（只读连接）
- 用户认证 + 限流
