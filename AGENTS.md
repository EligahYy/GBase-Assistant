# GBase 8a Agent 数据库助手 — AGENTS.md

> 本文件面向 AI 编码 Agent。如果你正在阅读此文件，说明你对该项目一无所知。以下信息均基于项目实际代码和配置，而非假设。

---

## 项目概述

**GBase 8a Agent 数据库助手** 是一个面向内部团队的 AI 数据库助手。用户通过自然语言中文对话，系统生成兼容国产 GBase 8a MPP 数据库的 SQL 查询，或回答 GBase 8a 相关的技术问题。

- **当前阶段**：Phase 1（MVP 已闭环，核心功能已实现并可用）
- **目标用户**：<50 人的内部产品/研发/测试团队
- **部署方式**：单机部署，前后端分离
- **主要语言**：中文（文档、注释、UI、Prompt 均以中文为主）

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
- **向量数据库**：当前未引入（Phase 3 计划引入 Qdrant）
- **知识库**：文件驱动（`knowledge/` 目录下的 YAML/JSONL/JSON）

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
├── backend/                   # FastAPI 后端
│   ├── pyproject.toml         # uv 项目配置、依赖、ruff 配置、pytest 配置
│   ├── uv.lock                # uv 锁定文件
│   ├── app/
│   │   ├── main.py            # FastAPI 应用工厂与启动事件
│   │   ├── config.py          # Pydantic Settings，读取 .env
│   │   ├── database.py        # SQLite async engine + session factory
│   │   ├── protocols.py       # 核心接口定义（SchemaRetriever/LLMClient 等 Protocol）
│   │   ├── dependencies.py    # FastAPI 依赖注入绑定
│   │   ├── api/
│   │   │   ├── router.py      # 路由注册
│   │   │   ├── chat.py        # 聊天 API（POST /chat, POST /chat/stream, 对话 CRUD）
│   │   │   ├── connections.py # 数据库连接管理 CRUD
│   │   │   └── health.py      # 健康检查
│   │   ├── chains/
│   │   │   ├── sql_chain.py   # Text-to-SQL 生成链（含自纠错重试）
│   │   │   ├── qa_chain.py    # 知识问答链
│   │   │   └── intent.py      # 意图分类（sql / qa / general）
│   │   ├── sql/
│   │   │   ├── dialect.py     # sqlglot GBase8A 方言定义
│   │   │   └── validator.py   # SQL 语法 + 方言合规 + Schema 交叉引用验证
│   │   ├── llm/
│   │   │   ├── client.py      # LiteLLM 封装（complete/stream）
│   │   │   └── prompts.py     # Prompt 模板管理
│   │   ├── knowledge/
│   │   │   └── loader.py      # 知识库加载器（FileExampleRetriever 等）
│   │   ├── models/
│   │   │   ├── connection.py  # DbConnection ORM
│   │   │   ├── conversation.py# Conversation ORM
│   │   │   └── message.py     # Message ORM（token_usage 用 Text 存 JSON）
│   │   └── schemas/
│   │       ├── chat.py        # ChatRequest/ChatResponse/MessageResponse Pydantic schema
│   │       └── connection.py  # ConnectionCreate/Update/Response schema
│   ├── config/
│   │   └── models.yaml        # LLM 模型配置（当前未实际使用，配置在 .env 中）
│   ├── alembic/               # 数据库迁移目录（当前仅有骨架，无实际迁移脚本）
│   └── tests/
│       └── __init__.py        # ⚠️ 注意：当前测试目录几乎为空，无实际测试用例
│
├── frontend/                  # Vue 3 前端
│   ├── package.json           # npm 配置，Node 引擎要求 ^20.19.0 || >=22.12.0
│   ├── vite.config.ts         # Vite 配置（含 @ -> src 别名）
│   ├── tsconfig*.json         # TypeScript 配置
│   ├── src/
│   │   ├── main.ts            # 应用入口：Pinia + Router + Naive UI
│   │   ├── App.vue            # 根组件（含 sidebar 开关逻辑和全局 CSS 变量）
│   │   ├── router/index.ts    # 路由定义（目前仅有 HomeView）
│   │   ├── stores/
│   │   │   ├── chat.ts        # 对话状态管理（消息列表、流式消息处理）
│   │   │   ├── connection.ts  # 数据库连接状态
│   │   │   └── counter.ts     # 示例 store（可忽略）
│   │   ├── api/
│   │   │   ├── client.ts      # Axios 实例（baseURL: localhost:8000/api）
│   │   │   ├── chat.ts        # 聊天 API 封装（含 SSE stream）
│   │   │   └── connections.ts # 连接管理 API 封装
│   │   ├── components/
│   │   │   ├── chat/
│   │   │   │   ├── ChatPanel.vue       # 聊天主面板（输入、消息列表、空状态提示）
│   │   │   │   ├── MessageBubble.vue   # 单条消息气泡（含流式光标）
│   │   │   │   └── SqlBlock.vue        # SQL 代码块展示 + 复制按钮
│   │   │   ├── layout/
│   │   │   │   └── Sidebar.vue         # 对话历史侧栏（新建/重命名/删除）
│   │   │   └── icons/...      # 示例图标组件（可忽略）
│   │   ├── views/
│   │   │   ├── HomeView.vue   # 首页（仅挂载 ChatPanel）
│   │   │   └── AboutView.vue  # 示例页面（可忽略）
│   │   └── composables/
│   │       ├── useSSE.ts      # SSE 流式请求封装
│   │       └── useContentParser.ts  # 实时解析 ```sql...``` 代码块
│   └── public/                # 静态资源
│
├── knowledge/                 # GBase 8a 知识库（文件驱动）
│   ├── dialect_rules/
│   │   ├── unsupported_features.yaml  # 不支持的特性清单
│   │   ├── syntax_differences.yaml    # 语法差异与示例
│   │   └── function_mapping.yaml      # 函数兼容性映射
│   ├── examples/
│   │   └── sql_examples.jsonl         # Few-shot NL→SQL 示例（约 10 条）
│   └── docs/
│       └── faq.json                   # FAQ 知识库（JSON 数组）
│
└── deploy/                    # 部署配置（⚠️ 当前为空目录）
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

复制 `.env.example` 为 `backend/.env`，至少配置一个 LLM API Key：

```bash
DEEPSEEK_API_KEY=sk-xxx
DASHSCOPE_API_KEY=sk-xxx
OPENAI_API_KEY=sk-xxx
ANTHROPIC_API_KEY=sk-xxx

DATABASE_URL=sqlite+aiosqlite:///./data/app.db
DEFAULT_MODEL=deepseek/deepseek-chat
CORS_ORIGINS=["http://localhost:5173"]
DEBUG=true
```

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

**⚠️ 当前状态：测试目录几乎为空。**

- `backend/tests/` 下仅有 `__init__.py`，无任何实际测试用例
- 项目文档（`CLAUDE.md`）中规划了以下测试，但尚未实现：
  - `test_sql_validator.py` — SQL 方言验证测试
  - `test_sql_chain.py` — SQL 生成链路测试（Mock LLM）
  - `test_api.py` — API 集成测试

### 测试运行方式

```bash
cd backend && uv run pytest -v
```

pytest 配置已写在 `pyproject.toml` 中：

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

如果你需要添加测试，请遵循以下约定：
- 单元测试必须 Mock 外部 LLM API 调用（不依赖真实网络）
- 集成测试如需真实 LLM，标记 `@pytest.mark.integration`
- SQL 验证测试需准备 GBase 8a 合法/非法 SQL 各 20+ 条

---

## 核心架构模式

### Protocol 驱动设计（最重要的约束）

`backend/app/protocols.py` 定义了所有核心抽象接口：

- `SchemaRetriever` — Schema 检索
- `ExampleRetriever` — Few-shot 示例检索
- `KnowledgeRetriever` — 知识库检索
- `LLMClient` — LLM 调用（`complete` + `stream`）
- `ChatChain` — 对话链抽象

**规则**：
- 所有 chain 函数必须通过参数接收 Protocol 实例
- `dependencies.py` 负责将 Protocol 绑定到具体实现
- 后续升级（如引入 Qdrant、LangGraph）时，**只改 `dependencies.py`，不改调用方代码**

### Intent 分类 + Chain 路由

用户消息首先经过 `intent.classify_intent()` 判断意图：
- `"sql"` → `sql_chain.run_sql_chain()` / `stream_sql_chain()`
- `"qa"` → `qa_chain.run_qa_chain()` / `stream_qa_chain()`
- `"general"` → 直接调用 LLM 通用回复

### SQL 生成与验证流程

```
用户输入
  → 加载方言规则（YAML）
  → Schema 检索（当前全量返回 db_connection.schema_ddl）
  → Few-shot 检索（当前返回 sql_examples.jsonl 前 5 条）
  → LLM 生成 SQL（temperature=0.1）
  → sqlglot 语法解析 + GBase 8a 方言合规检查 + Schema 交叉引用
  → 若验证失败且重试次数 < 3，追加纠错 prompt 重新生成
  → 返回 SQL + 中文解释
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
| 了解编码规范 | `CLAUDE.md` |
| 改 API 接口 | `backend/app/api/chat.py` |
| 改 SQL 生成逻辑 | `backend/app/chains/sql_chain.py` |
| 改 Prompt 模板 | `backend/app/llm/prompts.py` |
| 改 SQL 验证规则 | `backend/app/sql/validator.py` + `knowledge/dialect_rules/*.yaml` |
| 改前端聊天界面 | `frontend/src/components/chat/ChatPanel.vue` |
| 改流式接收逻辑 | `frontend/src/composables/useSSE.ts` |
| 改数据库模型 | `backend/app/models/*.py` |
| 添加 Few-shot 示例 | `knowledge/examples/sql_examples.jsonl` |
| 添加 FAQ 知识 | `knowledge/docs/faq.json` |

---

## 已知短板与下一步（供 Agent 参考）

1. **测试缺失**：整个项目目前没有任何自动化测试。添加测试是高优先级任务。
2. **部署目录为空**：`deploy/` 目录没有任何 Docker、Nginx 或 CI 配置。
3. **Alembic 迁移脚本为空**：`alembic/versions/` 下没有任何迁移文件。当前靠 `init_db()` 在启动时自动建表。
4. **模型配置未完全接入**：`backend/config/models.yaml` 存在但当前代码主要从 `.env` 读取 `DEFAULT_MODEL`，未深度使用 `models.yaml` 的 fallback 配置。
5. **前端路由极简**：目前仅有单一路由 `/`，没有设置页面、Schema 管理页面（虽然后端 API 已具备连接 CRUD）。
