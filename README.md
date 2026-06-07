# GBase 8a Assistant

面向产品、研发与测试人员的 GBase 8a 数据库 AI 助手。通过自然语言对话，自动生成 GBase 8a 兼容的 SQL，并解答数据库专业问题。

## 核心功能

- **Text-to-SQL**：统一 Agent 自主探索 Schema → 生成 SQL → 校验 → 沙箱执行
- **知识问答**：基于官方产品手册（向量检索 + RRF 融合 + Anti-Hallucination）的精准答疑
- **连接管理**：GBase 数据库连接状态实时监测（SSE 推送，零延迟感知）
- **数据库监控**：连接数/活跃SQL/运行时间/表概况一键查询
- **项目文件夹**：对话分组管理 + 批量操作（归档/删除/移动到文件夹）
- **流式可见性**：完整的 Agent 思考链（THINKING）+ 工具调用（TOOL_CALL）+ 步骤边界（STEP）
- **多轮对话**：上下文连贯的聊天与流式输出（AG-UI 标准事件协议）

## 架构

```
Vue 3 Chat UI ←── AG-UI SSE ──→ FastAPI Gateway
                                     │
                         LangGraph Unified ReAct Agent (v3.2)
                                     │
                    统一 Agent（全工具集，10 tools）
                     │                              │
                     │  submit_sql            final_answer
                     ↓                              ↓
              Validate Gate → Execute Gate        END
```

**v3.2 统一 Agent 架构**（当前版本）：
- **统一 ReAct Agent**：单个 Agent 持有全部工具，模型根据完整上下文自主决策调用哪些工具、以什么顺序。无独立 Supervisor/router——Prompt + Tools 即为路由机制
- **final_answer 显式终止**：Agent 必须调用 `final_answer` 工具结束，配合循环检测（同一工具+同参数 ≤ 2次）和三级终止策略（温和提醒→紧急提示→优雅降级），杜绝无限循环
- **Anti-Hallucination 知识检索**：`search_knowledge` 返回 status（found/partial/not_found），Prompt 强制 LLM 遵守——not_found 时严禁编造
- **确定性 SQL Gate**：`submit_sql` 提交后经过只读安全、方言和 Schema 三层验证，通过后才允许执行
- **天然多意图支持**：Agent 可在同一轮调用 Schema 工具 + Knowledge 工具，解决"查数据并解释概念"类复合请求
- **AG-UI 完整事件**：`RUN_STARTED` → `STEP_STARTED` → `THINKING_START/CONTENT/END` → `TOOL_CALL_START/RESULT/END` → `TEXT_MESSAGE_CONTENT` → `STEP_FINISHED` → `RUN_FINISHED`
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
│   │   ├── graph.py          # v3.2 统一 Agent 图（5节点）+ Runner
│   │   ├── schema_graph.py   # Schema Knowledge Graph（DDL 解析+检索）
│   │   ├── agents/           # Agent 定义
│   │   │   ├── unified_agent.py   # 统一 Agent（prompt + 10工具 + FinalAnswerTool）
│   │   │   ├── knowledge_agent.py # Knowledge Pipeline（search→answer，非 ReAct）
│   │   │   └── prompts.py        # 旧 prompt 占位
│   │   └── tools/            # 统一 Agent 工具集
│   │       ├── base.py           # ToolParameter 元数据
│   │       ├── schema_tools.py   # SearchSchemas / GetTableProfile / FindJoinPath
│   │       ├── sql_tools.py      # SubmitSQL / ExecuteSQL
│   │       ├── knowledge_tools.py # SearchKnowledgeTool
│   │       ├── glossary_tool.py  # QueryGlossary
│   │       ├── error_code_tool.py # LookupErrorCode
│   │       └── status_tool.py    # GetDatabaseStatus
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

## 许可证

MIT
