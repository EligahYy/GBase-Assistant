# GBase 8a Assistant

面向数据分析、研发和运维场景的 GBase 8a AI 数据库助手。系统将自然语言查询转换为受治理的 Query IR 和只读 SQL，并提供知识问答、连接管理、Schema 同步、结果摘要与可视化能力。

当前核心架构为 **v3.4 Semantic NL2SQL Graph**。它不再依赖自由循环的 ReAct Agent，而是通过确定性的 LangGraph 状态机、语义资产约束、分层 SQL 校验和有限修复预算控制准确性与安全性。

详细设计、代码导览和面试演示手册见 [ARCHITECTURE_INTERVIEW_GUIDE.md](ARCHITECTURE_INTERVIEW_GUIDE.md)。

## 核心能力

- **受治理的 Text-to-SQL**：自然语言先转换为 Query IR，再生成、验证和执行 SQL。
- **混合语义映射**：综合名称、别名、字符相似度、描述和可选向量相似度召回指标、维度与成员值。
- **无语义模型降级**：只有表结构时，可依据表名、字段名、类型、主外键和注释生成低置信度候选资产。
- **确定性约束**：模型只能选择召回到的指标、维度、过滤字段和可信 JOIN，不能自行发明业务定义。
- **分层 SQL 校验**：语义一致性、只读安全、单语句、方言、Schema 引用依次验证。
- **有限自动修复**：最多 4 个 SQL 候选、2 次数据库执行、同类错误最多重试 2 次。
- **多驱动执行**：支持 GBase Native 和本地 SQLite 演示驱动；JDBC/ODBC 为预留扩展位。
- **知识问答**：Qdrant 向量检索与本地全文检索结合，回答附带来源并在检索失败时降级。
- **AG-UI 流式响应**：步骤、思考状态、工具调用、答案 token、SQL 和结构化结果均通过 SSE 返回。
- **结果摘要与可视化**：模型只总结关键结论和取数逻辑，结构化结果由前端在图表、表格、原始数据间切换。

## 总体架构

```text
Vue 3 / Pinia / Naive UI
          |
          | POST /api/chat/stream (AG-UI SSE)
          v
FastAPI Chat Gateway
          |
          +-- 问候 ----------> 低延迟受限 LLM 回复
          +-- 监控 ----------> 数据库状态工具
          +-- 知识问答 ------> Hybrid RAG -> Grounded Answer
          |
          +-- 数据查询 ------> v3.4 Semantic NL2SQL Graph
                                  |
                                  v
 resolve -> build_context -> plan_query -> clarify / generate_sql
                                  |                    |
                                  |                    v
                                  +----------> verify_sql <-> refine_sql
                                                       |
                                                       v
                                                   execute_sql
                                                       |
                                                       v
                                                   build_answer
```

### SQL 查询链路

1. **请求路由**：明确的数据查询进入 NL2SQL；问候、监控和知识问答走独立快速路径。
2. **语义上下文构建**：选择业务模型，混合召回指标、维度、成员值，构建 `FocusedSchema` 和可信 JOIN。
3. **Query IR 规划**：LLM 理解自然语言并填写结构化槽位；代码重新绑定所有表达式和字段到受治理资产。
4. **澄清或生成**：存在真实歧义时先向用户确认；否则只基于 Query IR 与聚焦 Schema 生成 SQL。
5. **确定性验证**：检查 SQL 是否忠实实现 Query IR，并经过只读、方言和完整 Schema 校验。
6. **有限修复**：可修复错误进入受预算约束的 `refine_sql -> verify_sql` 回路，避免无限循环。
7. **只读执行**：通过 Connector 和 SQLSandbox 执行，最多读取 1000 行，聊天界面最多返回 50 行。
8. **结果呈现**：答案按 token 流式总结关键发现；SQL、语义逻辑和结果数据以结构化事件独立返回。

## 技术栈

| 层 | 技术 |
|---|---|
| 前端 | Vue 3、TypeScript、Pinia、Naive UI、Vite |
| API / 编排 | FastAPI、LangGraph、AG-UI SSE |
| LLM | LiteLLM，支持 DeepSeek、Qwen、OpenAI 等模型 |
| 语义层 | Semantic Model、Query IR、Hybrid Semantic Matcher、SchemaGraph |
| SQL | sqlglot、自定义 GBase 8a 规则、SQLSandbox |
| 目标数据库 | GBase Native、SQLite 本地演示 |
| 应用元数据 | SQLite + SQLAlchemy Async + Alembic |
| 检索 | Qdrant 向量检索 + ripgrep 文件检索降级 |
| 测试 | pytest、NL2SQL eval runner、ESLint、vue-tsc |

## 快速开始

### 1. 环境要求

- Python >= 3.12
- Node.js ^20.19.0 或 >= 22.12.0
- [uv](https://docs.astral.sh/uv/)
- 可选：Docker，用于启动 Qdrant

### 2. 安装与配置

```bash
make install
cp .env.example backend/.env
```

至少配置一个模型提供商，例如：

```dotenv
DEEPSEEK_API_KEY=sk-xxx
DEFAULT_MODEL=deepseek/deepseek-chat
DEBUG=true
SKIP_VECTOR_SYNC=true
```

`SKIP_VECTOR_SYNC=true` 适合首次演示。Qdrant 不可用时，知识问答会降级到本地文件检索。

### 3. 初始化应用元数据与 SQLite 演示库

```bash
make migrate
cd backend
TESTING=1 UV_CACHE_DIR=/tmp/gbase8a-uv-cache uv run python scripts/setup_sqlite_demo.py
cd ..
```

脚本会幂等创建：

- 目标数据库：`backend/data/nl2sql_demo.db`
- 连接：`sqlite-demo-sales`
- 语义模型：`sqlite-demo-sales-model`
- 五张电商样例表：`sales_regions`、`customers`、`products`、`orders`、`order_items`

### 4. 启动服务

```bash
# 终端 1
make dev-backend

# 终端 2
make dev-frontend
```

- 前端：`http://localhost:5173`
- API 文档：`http://localhost:8000/docs`，仅 `DEBUG=true` 时开启
- 健康检查：`http://localhost:8000/api/health`

可选启动 Qdrant：

```bash
docker compose -f deploy/docker-compose.yml up -d qdrant
```

## 演示问题

```text
你好
查询2025年销售总额
销售额和订单数
各区域销售额排行
产品销售额
订单状态
交易状态
查询销售
GBase 8a 支持窗口函数吗？
```

- “交易状态”用于展示同义词和语义召回。
- “查询销售”故意信息不足，应触发澄清而不是盲目生成 SQL。
- SQLite 演示数据中，2025 年销售总额为 `57246`，订单数为 `26`。

## 主要 API

| 端点 | 说明 |
|---|---|
| `POST /api/chat/stream` | AG-UI SSE 对话入口 |
| `GET /api/chat/conversations` | 对话历史与文件夹管理 |
| `GET/POST /api/connections` | 数据库连接管理 |
| `POST /api/connections/{id}/sync-schema` | 同步 Schema 并构建 SchemaGraph |
| `POST /api/connections/{id}/query` | 直接只读查询 |
| `GET /api/connections/status/stream` | 连接状态 SSE |
| `GET/POST /api/semantic-models` | 语义模型、指标、维度和 JOIN 管理 |
| `GET /api/health` | 应用、元数据数据库与 Qdrant 健康检查 |
| `POST /api/admin/reindex*` | 知识库重建 |
| `POST /api/tools/error-code` | 错误码查询 |

管理类接口使用 `X-Admin-Token`。未配置 `ADMIN_TOKEN` 时，仅 `DEBUG=true` 环境允许无 Token 调用。

## 项目结构

```text
backend/app/
├── agents/graph.py               # v3.4 NL2SQL 图、快速路径与 AG-UI Runner
├── agents/state.py               # 图状态定义
├── agents/schema_graph.py        # Schema 元数据图与字段角色推断
├── semantic/
│   ├── context_builder.py        # 语义上下文、FocusedSchema、可信 JOIN
│   ├── matcher.py                # 混合语义匹配
│   ├── schema_assets.py          # 无业务语义模型时的 Schema 候选资产
│   ├── planner.py                # 自然语言到受约束 Query IR
│   └── query_ir.py               # 结构化查询意图
├── sql/                          # 语义验证、方言验证、沙箱与错误分类
├── db_connectors/                # Native / SQLite 连接器
├── vector/                       # Qdrant 与混合知识检索
└── api/                          # Chat、Connection、Semantic Model 等 API

frontend/src/
├── composables/useSSE.ts         # AG-UI SSE 解码
├── stores/chat.ts                # 流式消息状态
└── components/chat/              # 活动时间线、SQL、图表与表格
```

## 验证命令

```bash
make test
make lint

cd backend
TESTING=1 uv run python -m evals.nl2sql.runner --mock

cd ../frontend
npm run type-check
npm run build
```

## 当前边界

- 已验证示例的相似度检索接口已预留，但当前 `_retrieve_examples()` 仍返回空列表。
- SQL 生成当前使用单候选逐步修复，尚未接入 DAIL-SQL 风格的多候选选择或专业 NL2SQL 模型。
- 只有表结构时可进行有限推断，但 `f1`、`amt2` 等不透明字段无法可靠恢复业务语义。
- 大 Schema 当前最多向规划器暴露 80 个降级候选，后续需要表级召回和分阶段重排。
- 意图路由目前是保守规则路由，不是训练后的意图分类器。
- 多轮上下文目前主要解析最新用户问题，尚未实现完整的 Query IR 增量改写。

## License

MIT
