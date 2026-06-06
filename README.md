# GBase 8a Assistant

面向产品、研发与测试人员的 GBase 8a 数据库 AI 助手。通过自然语言对话，自动生成 GBase 8a 兼容的 SQL，并解答数据库专业问题。

## 核心功能

- **Text-to-SQL**：自然语言 → ReAct Agent 自主探索 Schema → 生成 SQL → 校验 → 沙箱执行
- **知识问答**：基于官方产品手册（向量检索 + RRF 融合）的精准答疑
- **连接管理**：GBase 数据库连接状态实时监测（SSE 推送，零延迟感知）
- **数据库监控**：连接数/活跃SQL/运行时间/表概况一键查询
- **项目文件夹**：对话分组管理 + 批量操作（归档/删除/移动到文件夹）
- **流式可见性**：完整的 Agent 思考链（THINKING）+ 工具调用（TOOL_CALL）+ 步骤边界（STEP）
- **多轮对话**：上下文连贯的聊天与流式输出（AG-UI 标准事件协议）

## 架构

```
Vue 3 Chat UI ←── AG-UI SSE ──→ FastAPI Gateway
                                     │
                            LangGraph ReAct Multi-Agent (v3)
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
             Supervisor Agent   SQL Agent      Knowledge Agent
             (ReAct + 5 tools) (ReAct + 7 tools) (ReAct + 2 tools)
                    │                │                │
              动态委托路由    探索→生成→校验→执行→纠错  RAG 多步检索
```

**v3 ReAct 多智能体架构**（当前版本）：
- **3 个 Agent**：Supervisor（动态路由）+ SQL Specialist（端到端 NL2SQL）+ Knowledge Specialist（RAG 问答）
- **11 个标准化 Tool**：`search_schemas`、`get_table_profile`、`find_join_path`、`query_glossary`、`validate_sql`、`execute_sql`、`lookup_error`、`search_knowledge`、`get_database_status`、`delegate_to_sql_specialist`、`delegate_to_knowledge_specialist`
- **AG-UI 完整事件**：`RUN_STARTED` → `STEP_STARTED` → `THINKING_START/CONTENT/END` → `TOOL_CALL_START/RESULT/END` → `TEXT_MESSAGE_CONTENT` → `STEP_FINISHED` → `RUN_FINISHED`
- **自定义 ReAct 图**：替代 `langgraph.prebuilt.create_react_agent`，每个 Agent 的 tool 调用全过程流式可见
- **Schema Knowledge Graph**：DDL 语义解析 → 列角色推断 → JOIN 关系图 → 多策略检索

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + Naive UI + Pinia + Vite + TypeScript |
| 后端 | Python 3.12 + FastAPI + LangGraph |
| 数据库 | SQLite（aiosqlite）+ Alembic 迁移 |
| LLM | LiteLLM（支持 DeepSeek / Qwen / OpenAI 等多模型 fallback） |
| 向量数据库 | Qdrant（schemas / knowledge / sql_examples） |
| SQL 解析 | sqlglot + 自定义 GBase 8a 方言 + 沙箱执行 |
| 知识库 | GBase 8a 官方产品手册 V9.5.3（PDF 章节切片） |

## 快速开始

### 1. 环境准备

- Python >= 3.12
- Node.js ^20.19.0 || >=22.12.0
- [uv](https://docs.astral.sh/uv/)（Python 包管理）
- [poppler](https://poppler.freedesktop.org/)（PDF 知识库解析，`brew install poppler`）

### 2. 安装依赖

```bash
make install
```

### 3. 配置环境变量

```bash
cp .env.example .env
# 编辑 .env，填入至少一个 LLM API Key
```

### 4. 初始化数据库

```bash
make migrate
```

### 5. 准备知识库（可选）

将 GBase 8a 官方产品手册 PDF 放入 `knowledge/` 目录，服务器启动时自动切片索引到 Qdrant。

### 6. 启动开发服务

```bash
# 终端 1：启动后端
make dev-backend

# 终端 2：启动前端
make dev-frontend
```

前端默认地址：`http://localhost:5173`
后端 API 文档：`http://localhost:8000/docs`

## API 端点

| 端点 | 说明 |
|------|------|
| `POST /api/chat/stream` | AG-UI 多智能体流式聊天 |
| `GET /api/chat/conversations` | 对话历史列表 |
| `GET /api/connections` | 数据库连接管理 |
| `GET /api/connections/status/stream` | 连接状态实时推送 |
| `GET /api/health` | 系统健康检查 |
| `POST /api/admin/reindex-pdf` | 从 PDF 手册重建知识库索引 |
| `POST /api/admin/reindex` | 重建 JSON 知识库索引 |

## 项目结构

```
gbase8a-assistant/
├── backend/app/
│   ├── agents/
│   │   ├── state.py          # AgentState（namespace 隔离）
│   │   ├── graph.py          # v3 ReAct 图 + Agent Runner
│   │   ├── schema_graph.py   # Schema Knowledge Graph（DDL 解析+检索）
│   │   ├── agents/           # 🆕 Agent 实现
│   │   │   ├── react_agent.py    # 自定义 ReAct 工厂（流式事件发射）
│   │   │   ├── supervisor.py     # Supervisor Agent（动态路由）
│   │   │   ├── sql_agent.py      # SQL Agent（7 tools）
│   │   │   ├── knowledge_agent.py # Knowledge Agent（2 tools）
│   │   │   └── prompts.py        # System prompts
│   │   └── tools/            # 🆕 标准化 Tool 接口
│   │       ├── base.py           # AgentTool Protocol + ToolRegistry
│   │       ├── schema_tools.py   # SearchSchemas / GetTableProfile / FindJoinPath
│   │       ├── sql_tools.py      # ValidateSQL / ExecuteSQL
│   │       ├── glossary_tool.py  # QueryGlossary
│   │       ├── knowledge_tools.py # SearchKnowledge
│   │       ├── error_code_tool.py # LookupErrorCode
│   │       ├── status_tool.py    # GetDatabaseStatus
│   │       └── delegate_tools.py # DelegateToSQL / DelegateToKnowledge
│   ├── gateway/
│   │   └── ag_ui_encoder.py  # AG-UI 事件编码器（THINKING/TOOL_CALL/STEP）
│   ├── api/                  # FastAPI 路由
│   ├── services/             # 后台服务（健康检查、聊天、会话）
│   ├── llm/
│   │   ├── client.py         # LiteLLM 客户端
│   │   ├── adapter.py        # LiteLLM → LangChain 适配器
│   │   └── prompts.py        # 提示模板
│   ├── sql/                  # SQL 验证器 + 沙箱
│   ├── vector/               # Qdrant 客户端 + 检索器 + 索引
│   ├── knowledge/            # 知识加载器 + PDF 文档切片器
│   └── db_connectors/        # GBase 数据库驱动适配器
├── frontend/src/
│   ├── composables/          # useSSE / useAGUIClient / useTheme
│   ├── stores/               # Pinia 状态管理（含 ReAct streaming state）
│   ├── components/chat/
│   │   ├── ThinkingSection.vue  # 🆕 思考折叠区
│   │   ├── ToolCallCard.vue     # 🆕 Tool 调用卡片
│   │   └── MessageBubble.vue    # 消息气泡（含 Agent step indicator）
│   └── api/                  # API 客户端
├── knowledge/                # 官方产品手册 PDF
├── docs/superpowers/         # 架构规格 + 实施计划
├── deploy/                   # Docker / Nginx 部署配置
└── Makefile                  # 常用开发命令
```

## 常用命令

```bash
make install         # 安装前后端依赖
make dev-backend     # 启动后端开发服务
make dev-frontend    # 启动前端开发服务
make test            # 运行后端测试（TESTING=1）
make lint            # 代码检查
make migrate         # 执行数据库迁移
make migration msg="xxx"  # 生成迁移脚本
```

## v2 → v3 架构迁移

| 维度 | v2 | v3 |
|------|-----|-----|
| Agent 数量 | 7 个硬编码节点 | 3 个 ReAct Agent |
| 图节点 | 10 个 | 4 个（含 2 个 SubGraph） |
| 路由 | 关键词 `if/else` | LLM ReAct 动态 tool 选择 |
| Tool 接口 | 闭包工厂函数 | 标准化 `AgentTool` Protocol + `ToolRegistry` |
| SQL 路径 | 5 节点 pipeline（不可逆） | 1 Agent + 7 tools（自主循环） |
| 失败处理 | 硬 gate 阻断 + 盲重试 | Agent observe→diagnose→retry |
| 流式可见性 | 仅文本流 | 完整思考链 + Tool 调用 + Agent 步骤 |

## 许可证

MIT
