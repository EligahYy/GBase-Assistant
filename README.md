# GBase 8a Assistant

面向产品、研发与测试人员的 GBase 8a 数据库 AI 助手。通过自然语言对话，自动生成 GBase 8a 兼容的 SQL，并解答数据库专业问题。

## 测试git
测试vscode git

## 核心功能

- **Text-to-SQL**：自然语言 → GBase 8a 兼容 SQL + 中文解释
- **知识问答**：基于 GBase 8a 方言规则与文档的精准答疑
- **Schema 管理**：导入并管理目标数据库 DDL，辅助 SQL 生成
- **多轮对话**：支持上下文连贯的聊天与流式输出
- **SQL 校验**：基于 sqlglot 的语法与方言合规性验证

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3 + Naive UI + Pinia + Vite + TypeScript |
| 后端 | Python 3.12 + FastAPI + SQLAlchemy |
| 数据库 | SQLite（aiosqlite）+ Alembic 迁移 |
| LLM | LiteLLM（支持 DeepSeek / Qwen / OpenAI 等多模型 fallback） |
| SQL 解析 | sqlglot + 自定义 GBase 8a 方言 |

## 快速开始

### 1. 环境准备

- Python >= 3.12
- Node.js ^20.19.0 || >=22.12.0
- [uv](https://docs.astral.sh/uv/)（Python 包管理）

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

### 5. 启动开发服务

```bash
# 终端 1：启动后端
make dev-backend

# 终端 2：启动前端
make dev-frontend
```

前端默认地址：`http://localhost:5173`  
后端 API 文档：`http://localhost:8000/docs`

## 项目结构

```
gbase8a-assistant/
├── backend/           # FastAPI 后端
│   ├── app/           # 路由、模型、服务链、LLM 客户端
│   ├── config/        # 模型配置
│   ├── alembic/       # 数据库迁移
│   └── tests/         # 单元测试
├── frontend/          # Vue 3 前端
│   ├── src/           # 组件、页面、API 请求、状态管理
│   └── public/
├── knowledge/         # GBase 8a 知识库（方言规则、示例、FAQ）
├── deploy/            # Docker / Nginx 部署配置（Phase 3+）
├── Makefile           # 常用开发命令
└── ARCHITECTURE.md    # 详细架构设计文档
```

## 常用命令

```bash
make install         # 安装前后端依赖
make dev-backend     # 启动后端开发服务
make dev-frontend    # 启动前端开发服务
make test            # 运行后端测试
make lint            # 代码检查
make migrate         # 执行数据库迁移
make migration msg="xxx"  # 生成迁移脚本
```

## 许可证

MIT
