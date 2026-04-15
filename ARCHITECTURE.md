# GBase 8a Agent 数据库助手 — 技术架构规划

## 产品定义

**一句话描述**：面向产品/研发/测试人员的 GBase 8a 数据库 AI 助手，通过自然语言对话生成 SQL 并解答数据库专业问题。

**MVP 定义**：用户输入中文问题 → 系统输出 GBase 8a 兼容 SQL + 中文解释。这个闭环跑通即为 MVP。

**目标用户**：<50 人内部团队（产品经理、开发、测试）
**部署环境**：单机部署，可访问公网

---

## 技术栈

| 层 | 选型 | 理由 |
|---|---|---|
| **前端** | Vue 3 + Naive UI + Pinia + Vite | 国内生态主流，Naive UI 中文优先、TS 支持好 |
| **SQL 展示** | Monaco Editor | VSCode 同款，SQL 语法高亮+复制 |
| **后端** | Python 3.12 + FastAPI | AI/ML 生态对齐，async + 自动 OpenAPI 文档 |
| **应用数据库** | SQLite（aiosqlite） | 零运维、单文件、<50 用户足够。后续可迁移 PostgreSQL |
| **向量数据库** | Phase 1-2 不引入，Phase 3+ 引入 Qdrant | 早期数据量小，全量 schema 放 prompt 即可 |
| **LLM 调用** | LiteLLM | 统一接口，100+ 供应商，fallback 路由 |
| **Agent 编排** | Phase 1-2 简单函数链，Phase 3+ 按需引入 LangGraph | 避免过早框架绑定 |
| **SQL 解析** | sqlglot | 自定义方言支持，AST 遍历验证 |
| **包管理** | uv（后端）、npm（前端） | uv 极快，替代 pip |

---

## 系统架构

### Phase 1-2：极简架构（当前）

```
  Vue 3 SPA (Vite dev server)
       |
       | HTTP / SSE
       |
  FastAPI Server
       |
  +----+----+
  |         |
SQLite   LiteLLM → LLM API
(app DB)  (多模型)
```

### Phase 3+：完整架构（演进目标）

```
     Nginx (反向代理)
       |
  +----+----+
  |         |
Vue SPA   FastAPI
            |
     +------+------+
     |      |      |
  SQLite  Qdrant  LiteLLM
  (app)  (向量)   (多模型)
```

---

## Agent 架构：渐进式设计

### Phase 1-2：简单函数链（不引入 LangGraph）

```
用户输入
    │
    ▼
意图判断（prompt 内 few-shot 分类，非独立 Agent）
    │
    ├── SQL 相关 → sql_chain()
    │     ├── 注入 schema DDL + 方言规则 + few-shot 示例
    │     ├── LLM 生成 SQL
    │     ├── sqlglot 验证
    │     └── 失败则重试（最多 3 次）
    │
    ├── GBase 知识问答 → qa_chain()
    │     ├── 关键词匹配知识库（Phase 1 用 JSON 文件）
    │     └── LLM 生成回答
    │
    └── 其他 → 直接 LLM 回复（带角色约束 prompt）
```

**关键决策**：Phase 1-2 不用 Router Agent，用 system prompt 内的 few-shot 分类实现意图判断。不用 LangGraph，用普通 async 函数组合。降低 50% 的代码复杂度。

### Phase 3+：按需引入 LangGraph

当以下条件出现时才引入 LangGraph：
- Agent 之间需要复杂的状态传递和条件跳转
- 需要 checkpoint/resume 能力
- 需要人工审批节点（human-in-the-loop）

---

## Text-to-SQL Pipeline

### Phase 1 实现（极简版）

```
用户自然语言
    │
    ▼
[1] 构造 Prompt：
    - System: GBase 8a 方言规则（从 YAML 加载）
    - System: 目标数据库 Schema DDL（全量注入）
    - Few-shot: 硬编码 10-20 个高质量 NL→SQL 示例
    - User: 用户问题
    │
    ▼
[2] LLM 生成 SQL
    │
    ▼
[3] sqlglot 验证
    - 语法解析
    - GBase 8a 方言合规检查
    - 表/列名交叉引用（与 schema 比对）
    │
    ├── 通过 → 输出 SQL + 中文解释
    └── 失败 → 将错误信息追加到 prompt，重新生成（最多 3 次）
```

### Phase 3 演进（完整版）

在 Phase 1 基础上增加：
- Schema Linking：向量化检索相关表/列（替代全量注入）
- Few-shot 检索：从 Qdrant 检索相似示例（替代硬编码）
- 更完善的自纠错（分析错误类型，针对性修复）

---

## GBase 8a 方言处理

**从 Phase 1 第一天就建立方言规则**，这是 SQL 生成准确率的根基。

### 三层防线

1. **Prompt 层**：system prompt 显式列出 GBase 8a 约束，从 `knowledge/dialect_rules/*.yaml` 模板化生成
2. **验证层**：sqlglot 自定义 GBase 8a 方言（继承 MySQL + 覆写），AST 级别检查
3. **示例层**：所有 few-shot 示例均为验证过的 GBase 8a SQL

### 核心方言规则（Phase 1 必须覆盖）

```yaml
# knowledge/dialect_rules/unsupported_features.yaml
unsupported:
  - feature: TRIGGER
    description: GBase 8a 不支持触发器
    mysql_equivalent: CREATE TRIGGER
  - feature: FOREIGN_KEY_CONSTRAINT
    description: 语法接受但不强制执行
  - feature: LOCK_TABLES
    description: 不支持 LOCK TABLES / FOR UPDATE
  - feature: STORED_PROCEDURE  # 有限支持
    description: 支持基本存储过程，不支持游标
  - feature: AUTO_INCREMENT
    description: 支持但在分布式表上行为不同

syntax_differences:
  - name: DISTRIBUTED_BY
    description: 建表时指定分布键
    example: "CREATE TABLE t (id INT) DISTRIBUTED BY ('id')"
  - name: REPLICATED
    description: 创建复制表（每个节点完整副本）
    example: "CREATE TABLE dim (id INT) REPLICATED"
  - name: LIMIT_OFFSET
    description: 支持 LIMIT offset, count 语法（同 MySQL）
```

---

## 知识库方案

### Phase 1：文件驱动（无向量数据库）

```
knowledge/
├── dialect_rules/
│   ├── unsupported_features.yaml   # 不支持的特性
│   ├── syntax_differences.yaml     # 语法差异
│   └── function_mapping.yaml       # 函数兼容性
├── examples/
│   └── sql_examples.jsonl          # 已验证 NL→SQL 对（10-50 条起步）
└── docs/
    └── faq.json                    # 常见问题及答案（结构化 JSON）
```

- SQL 生成：从 YAML 加载方言规则注入 prompt + 从 JSONL 加载 few-shot 示例
- 知识问答：从 `faq.json` 关键词匹配，匹配到则注入 context 给 LLM

### Phase 3+：RAG 升级

- 引入 Qdrant 向量数据库
- 文档分块 + bge-m3 embedding
- 语义检索替代关键词匹配
- Cross-encoder re-rank 精排

---

## 数据模型（SQLite）

```sql
-- 数据库连接配置（存储目标 GBase 8a 的 schema 信息）
CREATE TABLE db_connections (
    id TEXT PRIMARY KEY,           -- UUID string
    name TEXT NOT NULL,
    host TEXT,
    port INTEGER DEFAULT 5258,
    database_name TEXT,
    description TEXT,
    schema_ddl TEXT,                -- 完整 DDL（Phase 1 手动粘贴）
    is_active INTEGER DEFAULT 1,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- 对话
CREATE TABLE conversations (
    id TEXT PRIMARY KEY,
    title TEXT,
    db_connection_id TEXT REFERENCES db_connections(id),
    model_used TEXT,
    created_at TEXT DEFAULT (datetime('now')),
    updated_at TEXT DEFAULT (datetime('now'))
);

-- 消息
CREATE TABLE messages (
    id TEXT PRIMARY KEY,
    conversation_id TEXT REFERENCES conversations(id) ON DELETE CASCADE,
    role TEXT NOT NULL,             -- 'user' | 'assistant' | 'system'
    content TEXT NOT NULL,
    message_type TEXT,              -- 'sql' | 'qa' | 'general'
    sql_generated TEXT,
    sql_validated INTEGER,
    token_usage TEXT,               -- JSON string: {"prompt": N, "completion": N, "model": "..."}
    created_at TEXT DEFAULT (datetime('now'))
);

-- SQL 反馈（Phase 2+）
CREATE TABLE sql_feedback (
    id TEXT PRIMARY KEY,
    message_id TEXT REFERENCES messages(id),
    action TEXT NOT NULL,           -- 'accepted' | 'rejected' | 'modified'
    original_sql TEXT,
    modified_sql TEXT,
    feedback_note TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
```

---

## 多模型配置

```yaml
# backend/config/models.yaml
default_model: "deepseek/deepseek-coder"

models:
  sql_generation:
    primary: "deepseek/deepseek-coder"
    fallback:
      - "qwen/qwen2.5-coder-32b-instruct"
      - "openai/gpt-4o"
    temperature: 0.1
    max_tokens: 2048

  knowledge_qa:
    primary: "deepseek/deepseek-chat"
    fallback:
      - "qwen/qwen2.5-72b-instruct"
      - "openai/gpt-4o"
    temperature: 0.3
    max_tokens: 4096

providers:
  deepseek:
    api_key: "${DEEPSEEK_API_KEY}"
    api_base: "https://api.deepseek.com"
  qwen:
    api_key: "${DASHSCOPE_API_KEY}"
    api_base: "https://dashscope.aliyuncs.com/compatible-mode/v1"
  openai:
    api_key: "${OPENAI_API_KEY}"
```

---

## 项目结构

```
gbase8a-assistant/
├── ARCHITECTURE.md                 # 本文件（架构设计，保持稳定）
├── CLAUDE.md                       # 编码 Agent 指令文件（开发规范）
├── .env.example                    # 环境变量模板
├── Makefile                        # 常用开发命令
│
├── backend/
│   ├── pyproject.toml              # uv 项目配置
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                 # FastAPI 应用入口
│   │   ├── config.py               # Pydantic Settings（环境变量 + models.yaml）
│   │   ├── database.py             # SQLite 连接 + SQLAlchemy async engine
│   │   ├── api/
│   │   │   ├── __init__.py
│   │   │   ├── router.py           # 顶层路由注册
│   │   │   ├── chat.py             # POST /api/chat, GET /api/chat/stream
│   │   │   ├── connections.py      # 数据库连接管理 CRUD
│   │   │   └── health.py           # 健康检查
│   │   ├── chains/                 # Phase 1-2 用函数链（非 LangGraph）
│   │   │   ├── __init__.py
│   │   │   ├── sql_chain.py        # Text-to-SQL 核心链
│   │   │   ├── qa_chain.py         # 知识问答链
│   │   │   └── intent.py           # 意图分类
│   │   ├── sql/
│   │   │   ├── __init__.py
│   │   │   ├── dialect.py          # GBase 8a sqlglot 方言定义
│   │   │   └── validator.py        # SQL 验证（语法+Schema+方言）
│   │   ├── llm/
│   │   │   ├── __init__.py
│   │   │   ├── client.py           # LiteLLM 封装 + fallback
│   │   │   └── prompts.py          # Prompt 模板管理
│   │   ├── knowledge/
│   │   │   ├── __init__.py
│   │   │   └── loader.py           # 加载 dialect_rules + examples + faq
│   │   ├── models/                 # SQLAlchemy ORM
│   │   │   ├── __init__.py
│   │   │   ├── connection.py
│   │   │   ├── conversation.py
│   │   │   └── message.py
│   │   └── schemas/                # Pydantic 请求/响应
│   │       ├── __init__.py
│   │       ├── chat.py
│   │       └── connection.py
│   ├── config/
│   │   └── models.yaml             # LLM 模型配置
│   ├── alembic/                    # 数据库迁移
│   │   ├── alembic.ini
│   │   └── versions/
│   └── tests/
│       ├── test_sql_validator.py
│       ├── test_sql_chain.py
│       └── test_api.py
│
├── frontend/
│   ├── package.json
│   ├── vite.config.ts
│   ├── tsconfig.json
│   ├── src/
│   │   ├── main.ts
│   │   ├── App.vue
│   │   ├── router/index.ts
│   │   ├── stores/
│   │   │   ├── chat.ts
│   │   │   └── connection.ts
│   │   ├── api/
│   │   │   ├── client.ts           # Axios 实例 + SSE
│   │   │   └── chat.ts
│   │   ├── components/
│   │   │   ├── chat/
│   │   │   │   ├── ChatPanel.vue
│   │   │   │   ├── MessageBubble.vue
│   │   │   │   └── SqlBlock.vue    # SQL 展示 + 复制
│   │   │   └── layout/
│   │   │       ├── AppLayout.vue
│   │   │       └── Sidebar.vue
│   │   ├── views/
│   │   │   ├── ChatView.vue
│   │   │   └── SettingsView.vue
│   │   └── composables/
│   │       └── useSSE.ts
│   └── public/
│
├── knowledge/                      # GBase 8a 知识库（Phase 1 第一天就开始积累）
│   ├── dialect_rules/
│   │   ├── unsupported_features.yaml
│   │   ├── syntax_differences.yaml
│   │   └── function_mapping.yaml
│   ├── examples/
│   │   └── sql_examples.jsonl      # {"question": "...", "sql": "...", "tables": [...]}
│   └── docs/
│       └── faq.json                # [{"question": "...", "answer": "...", "category": "..."}]
│
└── deploy/                         # Phase 3+ 部署配置
    ├── docker-compose.yml
    ├── Dockerfile.backend
    ├── Dockerfile.frontend
    └── nginx.conf
```

---

## 开发阶段（优化后）

### Phase 1：MVP 闭环（Week 1-2）

**目标**：跑通"自然语言 → GBase 8a SQL + 解释"的最小闭环

**后端**：
- FastAPI 项目骨架 + SQLite + aiosqlite + Alembic
- LiteLLM 集成（先接 DeepSeek 一个模型）
- GBase 8a 方言规则 YAML（20+ 条核心规则）
- 10-20 条硬编码 Few-shot SQL 示例
- sql_chain：prompt 构造 → LLM 生成 → sqlglot 验证 → 自纠错
- qa_chain：关键词匹配 faq.json → LLM 生成回答
- intent 分类（prompt 内 few-shot，非独立 Agent）
- POST /api/chat 接口 + SSE 流式输出

**前端**：
- Vue 3 + Naive UI 项目初始化
- 基础聊天界面（ChatPanel + MessageBubble + SqlBlock）
- SSE 流式接收
- SQL 一键复制

**验收标准**：
- 能通过聊天界面输入"查询每个部门薪资最高的3名员工"，返回合法的 GBase 8a SQL
- 能输入"GBase 8a 支持触发器吗？"，返回准确的知识回答
- SQL 包含中文解释，可一键复制

### Phase 2：核心增强（Week 3-5）

**目标**：多轮对话 + Schema 管理 + SQL 验证增强

- 对话历史持久化（SQLite）
- 多轮上下文：滑动窗口 + 摘要压缩
- Schema 管理 UI：手动导入 DDL，存储到 db_connections
- SQL 验证增强：表/列名交叉引用
- 多模型配置 + fallback
- SQL 反馈机制（采纳/拒绝/修改）
- 对话列表侧栏

### Phase 3：智能增强（Week 6-9）

**目标**：RAG + 向量检索 + 完善 Agent

- 引入 Qdrant 向量数据库（此时 Docker 应已就绪）
- GBase 8a 文档入库 + RAG 检索
- Schema Linking 向量化（替代全量注入，支持大 Schema）
- Few-shot 动态检索（替代硬编码）
- 按需评估是否引入 LangGraph
- 错误码查询工具
- Schema 浏览器 UI

### Phase 4：打磨上线（Week 10-12）

- 长期记忆（用户查询模式学习）
- SQL 反馈闭环 → 自动丰富 Few-shot 库
- 管理后台（模型管理、知识库刷新）
- 可观测性（日志、Token 用量统计）
- 认证 + 限流
- 部署脚本（Docker Compose）

### Phase 5（未来）：SQL 执行

- 安全执行沙箱 + 只读连接
- 结果表格化展示
- 查询历史 + 保存查询

---

## 技术演进路径

每个 Phase 1 的简化选择都必须有清晰的升级路径。核心原则：**Phase 1 写的代码在升级时是"替换实现"而非"推倒重写"**。

### 接口先行：升级缝（Upgrade Seam）

Phase 1 在以下 5 个关键位置定义 Python Protocol，实现用最简方案，升级时只替换实现类：

```python
# app/protocols.py — Phase 1 就创建，所有模块依赖此接口

from typing import Protocol, AsyncIterator

class SchemaRetriever(Protocol):
    """Schema 检索接口。Phase 1: 全量返回; Phase 3: 向量检索"""
    async def retrieve(self, query: str, db_id: str) -> list[TableSchema]: ...

class ExampleRetriever(Protocol):
    """Few-shot 示例检索接口。Phase 1: 全量返回; Phase 3: 向量检索"""
    async def retrieve(self, query: str, top_k: int = 5) -> list[SQLExample]: ...

class KnowledgeRetriever(Protocol):
    """知识库检索接口。Phase 1: 关键词匹配; Phase 3: RAG 向量检索"""
    async def retrieve(self, query: str, category: str | None = None) -> list[KnowledgeChunk]: ...

class LLMClient(Protocol):
    """LLM 调用接口。Phase 1: 单模型; Phase 2: 多模型 fallback"""
    async def complete(self, messages: list[dict], **kwargs) -> str: ...
    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]: ...

class ChatChain(Protocol):
    """对话链接口。Phase 1: 函数链; Phase 3+: 可选 LangGraph"""
    async def run(self, message: str, context: ChatContext) -> ChatResult: ...
    async def stream(self, message: str, context: ChatContext) -> AsyncIterator[StreamChunk]: ...
```

### 5 条升级路径详解

#### 路径 1：SQLite → PostgreSQL

| 维度 | 分析 |
|---|---|
| **升级难度** | 低 |
| **触发条件** | Docker 就绪，或并发写入出现锁冲突 |
| **升级步骤** | 1) 改 `DATABASE_URL` 环境变量<br>2) `alembic upgrade head` 在新库执行迁移<br>3) 导出旧数据 / 或从零开始 |
| **Phase 1 注意事项** | SQLAlchemy ORM 抽象了数据库差异，但必须注意：<br>- Alembic 配置 `render_as_batch=True`（SQLite 不支持 ALTER DROP COLUMN）<br>- 不使用 SQLite 特有语法<br>- JSON 字段用 `Text` 类型 + 手动 `json.dumps/loads`，不用 PG 的 `JSONB` |
| **零成本保证** | ORM 模型、迁移脚本、业务代码均不需要修改，只改连接字符串 |

```python
# Phase 1: app/database.py
DATABASE_URL = "sqlite+aiosqlite:///./data/app.db"

# Phase 3+: 只改这一行
DATABASE_URL = "postgresql+asyncpg://user:pass@localhost:5432/gbase_assistant"
```

#### 路径 2：简单函数链 → LangGraph

| 维度 | 分析 |
|---|---|
| **升级难度** | 中（这是最高风险项） |
| **触发条件** | 需要复杂状态管理（checkpoint/resume）、human-in-the-loop、Agent 间条件跳转 |
| **风险点** | 如果 Phase 1 的 chain 函数签名和 LangGraph 的 node 签名差异大，升级成本高 |

**Phase 1 防护措施**：chain 函数必须遵循统一签名，使其可直接包装为 LangGraph node：

```python
# Phase 1: app/chains/sql_chain.py
async def sql_chain(message: str, context: ChatContext) -> ChatResult:
    """纯函数，输入消息+上下文，输出结果。无副作用。"""
    schema = await schema_retriever.retrieve(message, context.db_id)
    examples = await example_retriever.retrieve(message)
    prompt = build_sql_prompt(message, schema, examples, context)
    sql = await llm_client.complete(prompt)
    validation = validate_sql(sql, schema)
    if not validation.is_valid and context.retry_count < 3:
        # 自纠错
        context.retry_count += 1
        return await sql_chain(correction_message, context)
    return ChatResult(content=sql, sql=sql, validation=validation)

# Phase 3+: 包装为 LangGraph node（不修改原函数）
from langgraph.graph import StateGraph

def sql_node(state: ConversationState) -> ConversationState:
    """LangGraph node，包装已有的 sql_chain"""
    context = ChatContext.from_state(state)
    result = await sql_chain(state["messages"][-1].content, context)
    return {"sql_result": result.sql, "messages": [AIMessage(content=result.content)]}
```

**关键约束**：
- chain 函数必须是 `async def fn(message, context) -> result` 签名
- 不在 chain 内部操作全局状态或数据库 session
- ChatContext 设计要兼容 LangGraph State 的字段

#### 路径 3：无向量数据库 → Qdrant

| 维度 | 分析 |
|---|---|
| **升级难度** | 低 |
| **触发条件** | Schema 总量超过 prompt token 限制（约 50+ 张表），或 FAQ 超过 200 条 |
| **升级步骤** | 1) 安装 Qdrant（Docker）<br>2) 实现 `QdrantSchemaRetriever` / `QdrantExampleRetriever`<br>3) 在依赖注入处替换实现 |

```python
# Phase 1: 全量返回
class SimpleSchemaRetriever:
    async def retrieve(self, query: str, db_id: str) -> list[TableSchema]:
        """直接返回该 db 的所有表 schema"""
        return await db.get_all_schemas(db_id)

# Phase 3+: 向量检索（接口不变，只换实现）
class QdrantSchemaRetriever:
    async def retrieve(self, query: str, db_id: str) -> list[TableSchema]:
        """向量相似度检索最相关的 top-k 表"""
        embedding = await embed(query)
        results = await qdrant.search(collection="schemas", vector=embedding,
                                       filter={"db_id": db_id}, limit=10)
        return [TableSchema.from_qdrant(r) for r in results]
```

**零成本保证**：`SchemaRetriever` Protocol 在 Phase 1 就定义，chains 层只依赖接口。

#### 路径 4：硬编码 Few-shot → 动态检索

| 维度 | 分析 |
|---|---|
| **升级难度** | 低 |
| **触发条件** | 示例超过 50 条，或需要根据用户问题动态选择最相关示例 |

```python
# Phase 1: 全量加载
class FileExampleRetriever:
    def __init__(self):
        self.examples = load_jsonl("knowledge/examples/sql_examples.jsonl")

    async def retrieve(self, query: str, top_k: int = 5) -> list[SQLExample]:
        """返回前 top_k 条（或简单关键词匹配）"""
        return self.examples[:top_k]

# Phase 3+: 向量检索
class QdrantExampleRetriever:
    async def retrieve(self, query: str, top_k: int = 5) -> list[SQLExample]:
        embedding = await embed(query)
        return await qdrant.search("sql_examples", vector=embedding, limit=top_k)
```

#### 路径 5：Prompt 意图分类 → 独立 Router Agent

| 维度 | 分析 |
|---|---|
| **升级难度** | 低 |
| **触发条件** | 意图类型超过 5 种，或 prompt 内分类准确率不足 |

```python
# Phase 1: prompt 内分类
async def classify_intent(message: str) -> str:
    """调用 LLM 返回 intent"""
    response = await llm_client.complete([
        {"role": "system", "content": INTENT_PROMPT},
        {"role": "user", "content": message}
    ])
    return parse_intent(response)  # "sql" | "qa" | "general"

# Phase 3+: 如果需要，可包装为独立 Agent node
# 但函数签名不变，调用方不感知差异
```

### 升级时序总览

```
Phase 1 (Week 1-2)          Phase 2 (Week 3-5)         Phase 3 (Week 6-9)
─────────────────           ──────────────────          ──────────────────
SQLite ──────────────────── SQLite ─────────────────── → PostgreSQL (可选)
函数链 ──────────────────── 函数链 ─────────────────── → 评估 LangGraph
无向量库 ────────────────── 无向量库 ───────────────── → Qdrant
硬编码示例 ──────────────── 硬编码示例 ─────────────── → 向量检索
关键词匹配 FAQ ──────────── 关键词匹配 ────────────── → RAG
单模型 ──────────────────── 多模型 fallback ────────── → 多模型 + 健康监控
Prompt 意图分类 ──────────── Prompt 意图分类 ─────────── → 评估独立 Router
```

**每次升级都是"替换 Protocol 实现"，不改调用方代码。**

### 升级检查清单

进入每个新 Phase 前，检查：

- [ ] 当前 Phase 的所有 Protocol 实现是否满足需求？哪些需要升级？
- [ ] 升级项的新实现是否通过了原有单元测试？（接口不变，测试应直接通过）
- [ ] 是否有 Phase 1 的"临时方案"已成为性能瓶颈？
- [ ] 知识库（方言规则 + Few-shot）是否持续丰富？

---

## 关键设计约束

1. **MVP 优先**：每个 Phase 结束时都有可用的、可演示的产物
2. **接口先行**：Phase 1 就定义 Protocol，所有模块依赖接口而非实现
3. **渐进式复杂度**：先跑通简单方案，用实际问题驱动架构升级
4. **知识库第一天开始积累**：方言规则、Few-shot 示例从 Phase 1 就建，持续丰富
5. **升级零重写**：每次技术升级只替换实现，不改调用方代码
4. **可迁移数据库层**：SQLAlchemy ORM 抽象，SQLite→PostgreSQL 只需改连接字符串
5. **模型无关**：LiteLLM 抽象层，所有 LLM 调用通过统一接口，不硬编码任何模型

---

## 验证方式

1. **单元测试**：SQL 方言验证、sqlglot 方言检查、intent 分类
2. **链路测试**：NL → Prompt 构造 → SQL 生成 → 验证 → 输出（Mock LLM）
3. **E2E 测试**：前端聊天 → API → LLM → 返回（真实 LLM 调用）
4. **人工评测**：准备 30 个标准 NL→SQL 测试用例，评估准确率
