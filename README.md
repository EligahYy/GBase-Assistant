# GBase 8a Assistant

面向产品、研发与测试人员的 GBase 8a 数据库 AI 助手。通过自然语言对话，自动生成 GBase 8a 兼容的 SQL，并解答数据库专业问题。

## 核心功能

- **Text-to-SQL**：自然语言 → Schema Grounding → GBase 8a 兼容 SQL + 自动执行
- **知识问答**：基于官方产品手册（向量检索 + RRF 融合）的精准答疑
- **连接管理**：GBase 数据库连接状态实时监测（SSE 推送，零延迟感知）
- **数据库监控**：连接数/活跃SQL/运行时间/表概况一键查询
- **项目文件夹**：对话分组管理 + 批量操作（归档/删除/移动到文件夹）
- **SQL 校验与执行**：sqlglot 三层验证 + 沙箱安全执行
- **多轮对话**：上下文连贯的聊天与流式输出（AG-UI 标准事件协议）

## 架构

```text
Vue 3 Chat UI ←── AG-UI SSE ──→ FastAPI Gateway
                                     │
                              LangGraph Orchestration
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
              Schema Grounding  SQL Specialist  Knowledge Specialist
                    │                │                │
              Schema Graph    SQL Verifier     Hybrid RAG (Qdrant)
                               SQL Executor
```

**v2 多智能体架构**（当前版本）：
- **7 个 Agent**：Orchestrator（ReAct 循环）+ 6 个 Specialist
- **AG-UI 标准事件**：`RUN_STARTED` → `TOOL_CALL_START/END` → `TEXT_MESSAGE_CONTENT` → `RUN_FINISHED`
- **Schema Knowledge Graph**：DDL 语义解析 → 列角色推断 → JOIN 关系图 → 多策略检索
- **知识库**：GBase 8a 官方产品手册（PDF 章节切片 + Qdrant 向量索引）

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
│   ├── agents/          # LangGraph 多智能体（Orchestrator + Specialists）
│   │   ├── state.py     # AgentState 共享状态
│   │   ├── orchestrator.py  # 意图分类 + 路由
│   │   ├── schema_graph.py  # Schema Knowledge Graph
│   │   └── graph.py     # LangGraph 图构建 + Agent Runner
│   ├── gateway/         # AG-UI 事件编码器
│   ├── api/             # FastAPI 路由（v1 + v2）
│   ├── services/        # 后台服务（健康检查、聊天、会话）
│   ├── chains/          # LLM 链（SQL 生成、QA、意图分类）
│   ├── sql/             # SQL 验证器 + 沙箱
│   ├── vector/          # Qdrant 客户端 + 检索器 + 索引
│   ├── knowledge/       # 知识加载器 + PDF 文档切片器
│   ├── db_connectors/   # GBase 数据库驱动适配器
│   └── llm/             # LiteLLM 客户端 + 提示模板
├── frontend/src/
│   ├── composables/     # useSSE / useAGUIClient / useTheme
│   ├── stores/          # Pinia 状态管理
│   ├── components/      # Vue 组件
│   └── api/             # API 客户端
├── knowledge/           # 官方产品手册 PDF + v1_archive（旧模型生成内容）
├── docs/superpowers/    # 架构规格 + 实施计划
├── deploy/              # Docker / Nginx 部署配置
└── Makefile             # 常用开发命令
```

### Admin API：知识库索引手动触发

```bash
# PDF 产品手册索引（首次 ~5 分钟提取文本，后续秒级）
curl -X POST http://localhost:8000/api/admin/reindex-pdf

# JSON 知识库索引（FAQ/错误码/运维文档）
curl -X POST http://localhost:8000/api/admin/reindex

# 查看索引结果
curl http://localhost:8000/api/admin/feedback-stats
```

> 前提：PDF 手册需放在 `knowledge/` 目录下，`official_toc.json` 目录文件存在。debug 模式下无需 Token。

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
