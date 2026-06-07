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
                         LangGraph Hybrid Multi-Agent (v3)
                                     │
                              Planner Agent
                           (多任务计划 + 调度队列)
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
             SQL Specialist   Knowledge Pipeline  General Agent
             探索→submit_sql    Hybrid RAG→回答       通用对话
                    │
             Validate Gate → Execute Gate
```

**v3 混合多智能体架构**（当前版本）：
- **Planner + Specialist 协作队列**：Planner 可一次规划多个任务，框架顺序调度 SQL / Knowledge / General Specialist
- **确定性 SQL Gate**：SQL Specialist 只能通过 `submit_sql` 提交候选 SQL；只读安全、方言/Schema 验证通过后才允许执行
- **结构化状态**：SQL、验证结果、查询结果、知识来源写入 AgentState namespace，并通过 AG-UI `STATE_DELTA` 推送
- **可靠 RAG 管线**：Knowledge 使用 Hybrid Retrieval + RRF 的确定性检索回答流程
- **AG-UI 完整事件**：`RUN_STARTED` → `STEP_STARTED` → `THINKING_START/CONTENT/END` → `TOOL_CALL_START/RESULT/END` → `TEXT_MESSAGE_CONTENT` → `STEP_FINISHED` → `RUN_FINISHED`
- **混合协作图**：Planner 负责多任务编排，SQL Specialist 使用受控 ReAct，验证和执行由确定性 Gate 接管
- **Schema Knowledge Graph**：DDL 语义解析 → 列角色推断 → JOIN 关系图 → 多策略检索

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + Naive UI + Pinia + Vite + TypeScript |
| 后端 | Python 3.12 + FastAPI + LangGraph |
| 数据库 | SQLite（aiosqlite）+ Alembic 迁移 |
| LLM | LiteLLM（支持 DeepSeek / Qwen / OpenAI 等多模型 fallback） |
| 向量数据库 | Qdrant（schemas / knowledge / error_codes） |
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
│   │   │   ├── supervisor.py     # Planner Agent（多任务规划）
│   │   │   ├── sql_agent.py      # SQL Specialist 工具集
│   │   │   ├── general_agent.py  # General Specialist
│   │   │   └── prompts.py        # System prompts
│   │   └── tools/            # Specialist 工具
│   │       ├── base.py           # ToolParameter 元数据
│   │       ├── schema_tools.py   # SearchSchemas / GetTableProfile / FindJoinPath
│   │       ├── sql_tools.py      # SubmitSQL / ExecuteSQL
│   │       ├── glossary_tool.py  # QueryGlossary
│   │       ├── error_code_tool.py # LookupErrorCode
│   │       ├── status_tool.py    # GetDatabaseStatus
│   │       └── delegate_tools.py # DelegateToSQL / DelegateToKnowledge
│   ├── gateway/
│   │   └── ag_ui_encoder.py  # AG-UI 事件编码器（THINKING/TOOL_CALL/STEP）
│   ├── api/                  # FastAPI 路由
│   ├── services/             # 后台服务（健康检查、聊天、会话）
│   ├── llm/
│   │   ├── client.py         # LiteLLM 客户端
│   │   └── adapter.py        # LiteLLM → LangChain 适配器
│   ├── sql/                  # SQL 验证器 + 沙箱
│   ├── vector/               # Qdrant 客户端 + 检索器 + 索引
│   ├── knowledge/            # 知识加载器 + PDF 文档切片器
│   └── db_connectors/        # GBase 数据库驱动适配器
├── frontend/src/
│   ├── composables/          # useSSE / useAGUIClient / useTheme
│   ├── stores/               # Pinia 状态管理（含 ReAct streaming state）
│   ├── components/chat/
│   │   ├── AgentActivity.vue    # 思考和工具调用时间线
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
| Agent 数量 | 7 个硬编码节点 | Planner + 3 类 Specialist |
| 图节点 | 10 个 | 协作调度队列 + Specialist + 确定性 Gate |
| 路由 | 关键词 `if/else` | Planner 多任务计划 |
| Tool 管理 | 闭包工厂函数 | Specialist 显式工具集 |
| SQL 路径 | 5 节点 pipeline（不可逆） | Specialist 探索/纠错 + 确定性验证执行 |
| 失败处理 | 硬 gate 阻断 + 盲重试 | Gate 返回结构化错误，Specialist 定向修复 |
| 流式可见性 | 仅文本流 | 完整思考链 + Tool 调用 + Agent 步骤 |

## 许可证

MIT
