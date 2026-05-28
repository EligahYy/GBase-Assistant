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
| 编排 | **LangGraph** StateGraph + AgentState（Orchestrator-Subagent 模式） |
| 事件协议 | **AG-UI** 标准 SSE（单 FastAPI 进程，无需 Node.js 中间层） |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy async + SQLite |
| LLM | LiteLLM（DeepSeek/Qwen/GPT-4o fallback） |
| 向量库 | Qdrant（schemas / knowledge / sql_examples） |
| 前端 | Vue 3 + Naive UI + Pinia + TypeScript |
| SQL 解析 | sqlglot + 自定义 GBase 8a 方言 + 沙箱执行 |

## 系统架构

```
Vue 3 Chat UI ←── AG-UI SSE ──→ FastAPI Gateway
                                     │
                            LangGraph Multi-Agent
                                     │
          ┌──────────────────────────┼──────────────────────────┐
          │                          │                          │
    Orchestrator             Schema Grounding          Knowledge Specialist
    (ReAct Loop)             (DDL语义图谱+检索)        (Hybrid RAG+RRF)
          │                          │
          │                   SQL Specialist
          │                   SQL Verifier
          │                   SQL Executor
          │
    General Specialist
```

**7 个 Agent：** Orchestrator（Think→Plan→Act→Observe→Decide）+ 6 个 Specialist。上下文通过 `AgentState` TypedDict 字段所有权隔离。

## 项目结构

```
gbase8a-assistant/
├── backend/app/
│   ├── agents/             # LangGraph 多智能体（v2 核心）
│   │   ├── state.py        # AgentState TypedDict（23 字段）
│   │   ├── orchestrator.py # 关键词意图分类 + 路由
│   │   ├── schema_graph.py # Schema Knowledge Graph（DDL解析+角色+关系+检索）
│   │   └── graph.py        # LangGraph 8 节点图 + AG-UI Runner
│   ├── gateway/
│   │   └── ag_ui_encoder.py # AG-UI 8 种标准 SSE 事件编码
│   ├── api/
│   │   ├── chat.py         # /api/chat/stream（AG-UI 多智能体）+ 对话 CRUD
│   │   ├── connections.py  # 连接管理 + SSE 状态流
│   │   ├── admin.py        # reindex / reindex-pdf / reindex-web
│   │   └── ...
│   ├── knowledge/
│   │   ├── document_chunker.py  # PDF 缓存 + MD 切片 + Qdrant 索引
│   │   ├── web_crawler.py       # Playwright gbase.cn 爬虫
│   │   └── loader.py            # 方言规则加载
│   ├── llm/                # LiteLLM 客户端 + Prompt 模板
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

### NL2SQL（v2 多智能体）

```
用户输入 → Orchestrator(意图分类) → Schema Grounding(多策略检索)
  → SQL Specialist(LiteLLM + prompt) → SQL Verifier(三层验证)
  → 失败则自纠错(最多3次) → SQL Executor(沙箱) → AG-UI SSE 响应
```

### 知识问答

```
用户输入 → Orchestrator(意图=qa) → Knowledge Specialist
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
