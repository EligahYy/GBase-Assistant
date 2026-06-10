# GBase 8a Assistant 架构与面试演示手册

本文档用于完整理解当前代码实现、演示项目和回答架构追问。内容以当前仓库代码为准，明确区分已实现能力、设计取舍和后续规划。

## 1. 一句话定位

GBase 8a Assistant 是一个把自然语言业务问题转换为**可解释、可验证、只读执行** SQL 的数据库助手，同时提供 GBase 产品知识问答、连接管理、Schema 同步和查询结果可视化。

它最重要的工程特点不是“让模型自由写 SQL”，而是把模型放进受治理的流水线：

```text
自然语言 -> 语义资产召回 -> Query IR -> SQL -> 确定性验证 -> 有限修复 -> 只读执行
```

## 2. 面试开场怎么讲

### 30 秒版本

项目最初采用自由 ReAct Agent，通过 step 数量限制模型循环，但 NL2SQL 的结果不稳定：模型会过度探索、猜字段、错误 JOIN，失败后还可能重复尝试。当前 v3.4 把 SQL 查询改造成确定性 LangGraph 状态机，引入业务语义模型和 Query IR。LLM 只负责语义理解和 SQL 候选生成，指标表达式、字段、JOIN、只读安全、Schema 引用和修复次数都由代码控制。这样把不可控的 Agent loop 转换成可观测、可评估、可治理的 SQL 编译流水线。

### 3 分钟版本

系统接收用户问题后先走轻量路由：问候、监控、知识问答和数据查询分别处理。数据查询进入 v3.4 NL2SQL 图。

第一阶段是语义链接。系统优先使用人工治理的语义模型，包括指标、维度、成员值和 JOIN；匹配算法综合名称、别名、字符 n-gram、描述和可选 embedding。如果客户只有表结构，系统会根据表名、字段名、类型、主外键和注释生成低置信度候选，但明确记录推断假设。

第二阶段是 Query IR。模型不直接写 SQL，而是先把问题填入结构化槽位。代码随后把模型输出重新绑定到受治理定义，拒绝模型编造的指标、字段、过滤条件和 JOIN。

第三阶段才生成 SQL。SQL 必须同时通过语义一致性、只读沙箱、单语句、方言和完整 Schema 校验。可修复错误进入有限循环，最多 4 个候选、2 次执行、同类错误 2 次。验证成功后通过 GBase 或 SQLite Connector 只读执行。

最后，结果数据通过 AG-UI `STATE_DELTA` 交给前端展示，LLM 只流式输出关键结论和取数逻辑，避免 Markdown 表格与可视化重复。

## 3. 为什么从自由 ReAct 改成结构化图

### 原架构的问题

- step 上限只能阻止无限循环，不能保证每一步做对。
- 模型同时承担意图识别、Schema 探索、业务口径理解、SQL 生成和纠错，责任过重。
- “发现字段不存在后再试一次”会消耗 token 和延迟，仍可能换一种方式继续猜。
- 只校验 SQL 语法无法判断 SQL 是否忠实表达用户意图。
- 每次请求临时探索 Schema，缺乏稳定的业务语义层。

### 当前架构的核心取舍

| 问题 | 当前方案 |
|---|---|
| 如何避免自由循环 | 固定 LangGraph 节点和条件边 |
| 如何防止模型发明业务口径 | Semantic Model + QueryPlanner `_constrain_ir` |
| 如何验证 SQL 真的回答了问题 | Query IR + SemanticValidator |
| 如何避免危险 SQL | SQLSandbox 只读检查、单语句检查 |
| 如何控制修复成本 | 候选、执行、同错误指纹三种预算 |
| 如何支持新数据库 | SchemaGraph 自动候选资产，置信度降级 |
| 如何解释结果 | Query IR 生成取数逻辑，结构化结果独立展示 |

## 4. 系统总览

```text
Browser
  |
  v
Vue Chat UI
  |  useSSE / AG-UI events
  v
POST /api/chat/stream
  |
  v
run_agent_with_ag_ui
  |
  +-- exact greeting --> greeting LLM, 4s 总预算
  +-- monitoring -----> GetDatabaseStatusTool
  +-- knowledge ------> HybridKnowledgeRetriever -> grounded LLM answer
  +-- no connection --> 提示选择连接
  |
  +-- NL2SQL ---------> Semantic NL2SQL Graph
                           |
                           +-> SQLSandbox -> DatabaseConnector
                           |                  +-> Native GBase
                           |                  +-> SQLite
                           |
                           +-> AG-UI STATE_DELTA / token stream
```

### 主要运行时组件

| 组件 | 职责 | 代码入口 |
|---|---|---|
| FastAPI | API、生命周期、CORS | `backend/app/main.py` |
| Chat Gateway | 保存对话并转发 SSE | `backend/app/api/chat.py` |
| NL2SQL Runner | 快速路径、图执行、AG-UI 编码 | `backend/app/agents/graph.py` |
| SemanticContextBuilder | 构造语义候选与聚焦 Schema | `backend/app/semantic/context_builder.py` |
| QueryPlanner | NL 到受约束 Query IR | `backend/app/semantic/planner.py` |
| SemanticValidator | 校验 SQL 是否实现 Query IR | `backend/app/sql/semantic_validator.py` |
| SQLSandbox | 只读与执行边界 | `backend/app/sql/sandbox.py` |
| Connector Factory | 选择 GBase / SQLite 驱动 | `backend/app/db_connectors/connector_factory.py` |
| AG-UI Encoder | 把内部事件编码为 SSE | `backend/app/gateway/ag_ui_encoder.py` |
| Chat UI | 流式文本、活动、SQL、图表和表格 | `frontend/src/components/chat/` |

## 5. 请求路由链路

入口是 `run_agent_with_ag_ui()`。当前路由是保守规则路由，不是 LLM 分类器。

### 问候快速路径

- 只对清洗后的精确问候词触发，例如“你好”“谢谢”。
- 交给 `greeting` 任务模型自然回复，不使用固定模板。
- 模型调用超时 3 秒，整条路径超时 4 秒，不走 fallback 链。
- 超时或异常时返回安全兜底，不声称查询过数据库。

### 监控快速路径

匹配“连接状态”“慢查询”“活跃查询”等模式后调用 `GetDatabaseStatusTool`。这条链路是确定性工具调用，不进入 NL2SQL。

### 知识问答路径

“如何”“什么是”“支持”“语法”“报错”等问题进入知识问答。系统执行混合检索、查询扩展和来源合并，再让模型基于检索结果回答。

### NL2SQL 路径

- 明确包含“查询”“统计”“排行”“销售额”等数据意图时进入。
- 存在活动数据库连接时，短业务词如“订单状态”也默认进入 Schema linking。
- 没有活动连接时不生成 SQL，直接提示用户选择连接。

## 6. 完整 NL2SQL 状态图

```text
START
  |
resolve
  |
build_context
  |
plan_query
  |
  +-- planning error ------------------------> fail_answer -> END
  +-- unresolved ambiguity ------------------> clarify -----> END
  |
generate_sql
  |
verify_sql
  |
  +-- repairable and budget remains --------> refine_sql --+
  |                                                       |
  +-- invalid / budget exhausted -----------> fail_answer  |
  |                                                       |
  +-- valid --------------------------------> execute_sql <-+
                                                  |
                                                  +-- completed -> build_answer -> END
                                                  +-- repairable -> refine_sql
                                                  +-- fatal/budget exhausted -> fail_answer
```

### 节点逐个解释

#### `resolve`

从消息历史中取最新用户问题写入 `resolved_question`。当前实现主要解决“本轮究竟问了什么”，还不是完整的多轮 Query IR 改写器。

#### `build_context`

构造 `SemanticContext`：

- 选择语义模型。
- 召回指标、维度、成员值。
- 必要时补充时间维度。
- 构建最小 `FocusedSchema`。
- 保留完整 `schema_catalog` 供验证。
- 选择可信 JOIN。
- 计算置信度和歧义。

#### `plan_query`

LLM 根据问题和候选资产生成 Query IR JSON。随后 `_constrain_ir()` 用代码进行二次约束：

- 指标表达式替换为受治理表达式。
- 维度字段替换为受治理列引用。
- 未定义的指标、维度、过滤字段、时间字段进入 `unresolved`。
- JOIN 只能来自可信 JOIN 集合。
- `required_tables` 根据受治理资产重新构造，不能信任模型自由填写。
- 使用自动推断资产时写入 `assumptions` 并降低置信度。

#### `clarify`

存在真实歧义时停止 SQL 生成，向用户列出待确认问题和候选项。原则是“宁可确认，不带着高风险歧义执行”。

#### `generate_sql`

SQL 模型只接收用户问题、Query IR、FocusedSchema、Verified JOINs 和 Verified Examples。Verified Examples 接口已预留，但当前为空。模型被要求只输出 SQL，并只使用聚焦 Schema 中的表和列。

#### `verify_sql`

按顺序执行三层验证：

1. `SemanticValidator`：SQL 是否包含 Query IR 要求的指标、维度、过滤、时间、表和 JOIN。
2. `SQLSandbox`：首关键字、AST 危险操作、单语句检查。
3. `validate_sql`：语法、GBase 方言、分组/JOIN 警告、完整 Schema 引用。

注意：`FocusedSchema` 用于缩小模型上下文，`schema_catalog` 才是完整验证事实源。二者不能混用。

#### `refine_sql`

把当前 SQL 和验证错误交给 SQL 生成模型修正。修正后必须重新进入 `verify_sql`，不能直接执行。

#### `execute_sql`

调用 `SubmitSQLTool`，再次经过只读验证后，通过 Connector 执行。运行时错误会分类并生成错误指纹，连接类或不可修复执行错误不会被盲目重试。

#### `build_answer`

- 从 Query IR 生成可解释的取数逻辑。
- 最多给 LLM 20 行结果用于总结，避免上下文爆炸。
- 答案要求只输出关键结论，不输出 Markdown 表格或逐行清单。
- 最终回答按 token 流式发送。
- 完整结构化结果通过 `STATE_DELTA result` 独立发送。

## 7. AgentState 与修复预算

`backend/app/agents/state.py` 定义图中传递的类型化状态。重要字段包括 `resolved_question`、`semantic_context`、`query_ir`、`sql_candidate`、`sql_history`、`validation_report`、`query_result`、`should_clarify`、`should_retry`、`retry_hint`、`execution_count`、`final_response` 和 `semantic_logic`。

当前预算：

```python
MAX_SQL_CANDIDATES = 4
MAX_SQL_EXECUTIONS = 2
MAX_SAME_ERROR_RETRIES = 2
```

错误指纹由错误类别和 SQL 特征构成。相同错误反复出现时会提前停止，而不是仅依赖总 step 数。

## 8. 语义映射如何工作

### 8.1 受治理语义资产

| 资产 | 示例 | 用途 |
|---|---|---|
| SemanticModel | 电商销售分析 | 定义业务域和可用表 |
| SemanticMetric | 销售额 = `SUM(orders.pay_amount)` | 固定业务指标口径 |
| SemanticDimension | 区域 = `sales_regions.region_name` | 定义分析维度 |
| SemanticMember | 待付款 -> `pending` | 把用户词映射为真实过滤值 |
| SemanticJoin | `orders.region_id = sales_regions.region_id` | 控制多表关联 |

人工治理资产状态为 `verified`，优先级高于自动推断资产。

### 8.2 HybridSemanticMatcher

匹配器只对调用方提供的真实资产排序，不创建新资产。证据包括：

- 名称和别名的完全匹配或包含匹配。
- 中文字符 bigram Dice / containment 相似度。
- 描述、表达式、来源表或列引用相似度。
- 可选 embedding 余弦相似度。

精确名称和别名是强证据。Embedding 用于提升召回，但不能独立产生高置信度匹配，避免仅凭向量相近把不同业务指标绑定在一起。

成员值可能包含客户数据，因此在线请求路径不会把成员值发送给外部 embedding 服务。

### 8.3 多意图与歧义

- 问题包含“和、与、以及、分别”等词，并有多个强匹配时，按多意图保留多个资产。
- 多个高分且接近的候选会形成歧义。
- 弱字符重叠只用于召回，不应该直接要求用户在无意义候选间选择。
- 指标和维度存在明显强弱差时，会抑制另一类别的弱噪声。

### 8.4 只有表结构、没有 comment 怎么办

系统通过 `SchemaGraph` 和 `schema_assets.py` 做有边界的自动推断：

- 表名和字段名提供基础语义。
- 数据类型区分时间、数值和字符串。
- 主键可推断记录数指标。
- 数值度量字段可推断 `SUM` 候选。
- 主外键和关系可推断 JOIN 候选。
- 字段角色帮助识别主键、度量、时间维度和枚举。

这些资产标记为 `inferred`，使用时会写入假设并降低置信度。推断 JOIN 只有高置信度时才允许进入可信 JOIN。

这个方案能处理 `order_date`、`pay_amount`、`customer_id` 等具有技术语义的名称，但无法可靠理解 `f1`、`col_02`、`amt2` 的真实业务含义。面对不透明 Schema，正确方案是补充数据画像、样例值、用户确认或人工语义治理，而不是让模型猜。

### 8.5 FocusedSchema 与 schema_catalog

- `FocusedSchema`：只保留本次问题相关表列，减少模型 token 和误选范围。
- `schema_catalog`：保留业务模型内完整真实字段，供 SQL 引用校验。

如果只用 FocusedSchema 校验，合法但未进入提示词的列可能被误判；如果把完整 Schema 都给模型，大库会显著降低召回精度并增加成本。

## 9. Query IR 是什么

Query IR 是自然语言和 SQL 之间的结构化中间表示，类似编译器 IR。

```json
{
  "semantic_model_id": "sqlite-demo-sales-model",
  "query_type": "aggregate_rank",
  "metrics": [
    {"name": "销售额", "expression": "SUM(orders.pay_amount)"}
  ],
  "dimensions": [
    {"name": "区域", "column": "sales_regions.region_name"}
  ],
  "filters": [],
  "time_range": null,
  "order_by": [{"target": "销售额", "direction": "DESC"}],
  "limit": null,
  "required_tables": ["orders", "sales_regions"],
  "joins": [
    {"condition": "orders.region_id = sales_regions.region_id"}
  ],
  "assumptions": [],
  "unresolved": [],
  "confidence": 0.9
}
```

Query IR 的价值：

- 在生成 SQL 前显式表达用户意图。
- 能确定性判断 SQL 是否漏掉指标或过滤条件。
- 能展示“取数逻辑”，提高可解释性。
- 能把歧义转成明确的澄清问题。
- 为未来多轮修改、缓存和评估提供稳定接口。

## 10. SQL 安全与正确性

### 10.1 语义一致性

`SemanticValidator` 使用 SQL AST 对比 Query IR，检查指标、维度、过滤、时间范围、表和 JOIN 是否一致。

### 10.2 只读安全

`SQLSandbox` 负责：

- 只允许 `SELECT`、`SHOW`、`DESCRIBE`、`EXPLAIN` 等只读入口。
- 使用 AST 阻止写操作和危险语句。
- 禁止多语句拼接。
- 给执行设置超时和最大行数。

### 10.3 方言、Schema 与执行边界

- `validate_sql()` 检查 GBase 8a 方言、语法、表列引用和常见分组/JOIN 问题。
- Schema 引用错误默认视为高风险，不让模型在错误字段名上反复猜测。
- Connector 默认读取最多 1000 行，聊天响应最多携带前 50 行。
- 默认执行超时 30 秒，SQLite 连接以 `mode=ro` 打开。
- 生产 GBase 还应使用数据库只读账号和资源组限制，形成纵深防御。

## 11. 数据库连接与 Schema 同步

| driver_type | 状态 | 说明 |
|---|---|---|
| `native` | 已实现 | GBase Native Connector |
| `sqlite` | 已实现 | 本地端到端演示和开发 |
| `manual` | 已实现 | 仅录入 DDL，不执行查询 |
| `jdbc` / `odbc` | 预留 | 工厂返回未实现 |

Schema 同步流程：

```text
Connector.fetch_schema
  -> 保存 DbConnection.schema_ddl
  -> DDL parser
  -> build_schema_graph_from_connection
  -> 可选 ingest_schemas 到 Qdrant
```

`SchemaGraph` 是进程内结构，用于表列元数据、字段角色和关系查询；连接记录中的 `schema_ddl` 是可持久化事实源。

## 12. 知识问答链路

知识问答不进入 NL2SQL 图：

```text
用户问题
  -> HybridKnowledgeRetriever
  -> 原问题检索 + 查询扩展检索
  -> 合并去重
  -> grounded prompt
  -> LLM 流式回答
  -> STATE_DELTA sources
```

Qdrant 可用时使用向量检索；不可用时回退到本地文件全文检索。主要集合为 `knowledge`、`schemas` 和 `error_codes`。未找到资料时不能编造产品能力。

## 13. 流式协议与前端展示

后端通过 AG-UI 风格 SSE 发送：

- `RUN_STARTED` / `RUN_FINISHED`
- `STEP_STARTED` / `STEP_FINISHED`
- `THINKING_START` / `THINKING_CONTENT` / `THINKING_END`
- `TOOL_CALL_START` / `TOOL_CALL_RESULT` / `TOOL_CALL_END`
- `TEXT_MESSAGE_CONTENT`
- `STATE_DELTA`

关键结构化状态：

| path | 内容 |
|---|---|
| `sql` | 当前 SQL 和验证状态 |
| `result` | columns、rows、row_count、耗时、截断标志 |
| `semantic_logic` | Query IR 转换的取数逻辑 |
| `sources` | 知识问答来源 |

前端把文本总结和结构化结果分开。多行且包含数值列的数据默认图表，用户可切换图表、表格和原始 JSON。模型提示词禁止重复输出 Markdown 表格。

## 14. 数据与持久化

系统有三类数据存储：

1. **应用元数据 SQLite**：连接、对话、消息、语义模型、知识文档状态等。
2. **目标业务数据库**：真实 GBase 或本地 SQLite 演示库。
3. **Qdrant**：知识、Schema 和错误码向量索引，可降级。

不要混淆两个 SQLite：

- `backend/data/app.db` 是助手自己的元数据库。
- `backend/data/nl2sql_demo.db` 是被查询的样例业务数据库。

## 15. 本地 SQLite 演示环境

### 创建环境

```bash
cp .env.example backend/.env
make migrate

cd backend
TESTING=1 UV_CACHE_DIR=/tmp/gbase8a-uv-cache uv run python scripts/setup_sqlite_demo.py
```

脚本会初始化元数据表、重建样例业务库、写入连接与治理资产，并构建内存 SchemaGraph。

### 样例业务模型

| 表 | 用途 |
|---|---|
| `orders` | 订单、支付金额、状态、日期 |
| `customers` | 客户、会员等级、注册时间 |
| `sales_regions` | 销售区域 |
| `products` | 产品、分类、供应商 |
| `order_items` | 订单商品、数量、小计 |

已治理指标包括销售额、订单数、平均订单金额、产品销量和产品销售额。

### 推荐演示脚本

1. “你好”：展示独立问候模型和流式输出。
2. “查询2025年销售总额”：展示时间解析、Query IR、SQL 验证、执行和摘要。
3. “销售额和订单数”：展示多指标意图。
4. “各区域销售额排行”：展示可信 JOIN、分组和排序。
5. “交易状态”：展示相近业务词的语义召回。
6. “查询销售”：展示歧义澄清，而不是错误执行。
7. “GBase 8a 支持窗口函数吗？”：展示知识问答和引用来源。

已知样例基准：

- 2025 年销售总额：`57246`
- 订单数：`26`

## 16. 模型与安全配置

模型任务在 `backend/config/models.yaml` 中分开配置：

| task_type | 当前用途 |
|---|---|
| `sql_generation` | SQL 生成和修正 |
| `general` | Query Planner、结果摘要、知识问答 |
| `greeting` | 低延迟问候 |
| `intent_classification` | 已配置但当前路由未调用 |
| `embedding` | 语义匹配和向量索引 |

至少配置一个 API Key。演示时推荐只配置主模型，避免 fallback 带来的延迟和不可控差异。

```dotenv
DEEPSEEK_API_KEY=sk-xxx
DEFAULT_MODEL=deepseek/deepseek-chat
DEBUG=true
SKIP_VECTOR_SYNC=true
SECRET_KEY=replace-with-stable-secret
ADMIN_TOKEN=replace-with-admin-token
```

生产环境必须使用稳定的 `SECRET_KEY`，并为管理接口配置 `ADMIN_TOKEN`。管理请求通过 `X-Admin-Token` 认证。

## 17. 测试与评估

### 后端测试

```bash
make test
```

`TESTING=1` 会跳过 Qdrant 和 embedding 初始化，确保单元与回归测试稳定。重点测试包括：

- `test_v34_p0_regressions.py`
- `test_v34_p1_regressions.py`
- `test_semantic_matcher.py`
- `test_sqlite_connector.py`

### NL2SQL Eval

```bash
cd backend
TESTING=1 uv run python -m evals.nl2sql.runner --mock
```

Mock 模式验证评估链路和结构评分。当前真实 LLM 模式仍返回 skipped，因此还不能把它当成完整线上准确率基准。

### 前端验证

```bash
cd frontend
npm run lint
npm run type-check
npm run build
```

## 18. 当前已解决的高风险问题

- 由自由 Agent loop 改为有限状态图。
- Query Planner 输出类型不稳定导致 `Ambiguity(**str)` 崩溃的问题已做兼容和约束。
- SQL 使用不存在字段时会被完整 Schema 校验阻断。
- 模型不能自由覆盖指标表达式、维度字段和 JOIN。
- 错误修复具有候选数、执行数和同错误指纹预算。
- SQLite 连接以只读模式执行，便于 Mac 本地端到端验证。
- 管理接口统一增加 Token 权限检查。
- 结果摘要不再重复输出 Markdown 表格。
- 最终回答和知识回答恢复 token 流式输出。
- 问候使用独立低延迟配置，不再进入完整业务链路。

## 19. 当前局限与诚实回答

### Verified Example Retrieval 尚未接入

`SemanticContextBuilder._retrieve_examples()` 当前返回空列表。系统已预留 Verified Examples 提示位，但还没有真正实现类似 DAIL-SQL 的相似示例选择。

### 专业 NL2SQL 模型尚未接入

当前 SQL 生成仍使用通用 LiteLLM 任务模型。任务类型已经隔离，因此接入专业模型主要需要实现对应 Provider/服务并修改 `sql_generation.primary`，但生产前必须验证 GBase 方言适配、响应结构和延迟。

### 单候选生成

当前是一个候选生成、验证、修复的流程，不是多候选 self-consistency 或执行结果重排。

### 无注释 Schema 泛化有限

自动资产能提升冷启动，但业务含义不透明时不能保证准确。可靠生产方案需要数据画像、样例值发现、业务术语词典、人工确认和反馈闭环。

### 大 Schema 需要分阶段召回

当前降级候选最多 80 个。更大数据库应先做业务域/表级召回，再做列级召回和 rerank。

### 多轮 Query IR 修改仍待完善

当前 `resolve` 主要取最新问题。理想方案是把“改成按月”“只看华东”等追问转成对上一轮 Query IR 的确定性 patch。

### 意图路由仍是规则

规则路由可解释、延迟低，但跨域泛化有限。后续可加入轻量分类器，同时保留规则兜底和连接状态约束。

## 20. DAIL-SQL 思路如何接入

建议借鉴“示例选择 + 候选生成”的思想，而不是整套替换当前治理链路：

```text
当前 SemanticContext
  -> 检索同 Schema / 同意图 / 同 SQL skeleton 的已验证样例
  -> 专业 NL2SQL 模型生成 N 个候选
  -> 当前 SemanticValidator + SQLSandbox 过滤
  -> 执行或静态评分重排
  -> 最优候选进入现有执行链路
```

保持不变的部分：

- Semantic Model 和 Query IR
- 可信 JOIN
- SQLSandbox 和完整 Schema 校验
- 修复预算和错误指纹
- AG-UI 事件与结果呈现

需要新增的部分：

- 已验证案例表和反馈晋升流程
- Example Retriever
- SQL skeleton / complexity 特征
- 专业模型 Adapter
- 多候选 scorer 和离线准确率评估

## 21. 常见面试追问

### 为什么不直接让 LLM 根据完整 DDL 写 SQL？

完整 DDL 会扩大上下文和误选空间，而且无法表达“销售额到底用哪个字段、是否排除取消订单”等业务口径。语义模型解决业务定义，FocusedSchema 解决上下文噪声，Query IR 解决可验证性。

### Embedding 能解决所有语义映射吗？

不能。Embedding 适合召回，但相似不等于业务等价。当前设计要求强词法证据或受治理候选，并用 Query IR 和用户澄清处理风险。

### 如何防止 SQL 注入或写库？

模型输出先过首关键字、AST、单语句、方言和 Schema 校验；执行通过 SQLSandbox，SQLite 以只读 URI 打开。生产 GBase 还应使用数据库只读账号和资源组限制。

### 为什么错误修复不无限重试？

重复失败通常意味着上下文或业务口径缺失，而不是“再问一次模型”就能解决。有限预算可控制延迟、成本和数据库压力，并把不可解决问题转为用户澄清。

### 如何衡量 NL2SQL 效果？

不能只看 SQL 字符串完全一致。应分层测量语义资产召回率、Query IR 槽位准确率、表列和 JOIN 准确率、执行成功率、结果等价准确率、澄清正确率、平均 LLM 调用数、延迟和成本。

### 为什么保留 SQLite 驱动？

Mac 本地无法方便部署 GBase 8a。SQLite 驱动让语义链接、Query IR、SQL 验证、执行、流式事件和前端展示都能端到端验证；它不是用 SQLite 替代生产 GBase，而是提供可重复的开发与演示环境。

## 22. 代码阅读顺序

1. `backend/app/agents/graph.py`
2. `backend/app/agents/state.py`
3. `backend/app/semantic/context_builder.py`
4. `backend/app/semantic/matcher.py`
5. `backend/app/semantic/schema_assets.py`
6. `backend/app/semantic/planner.py`
7. `backend/app/semantic/query_ir.py`
8. `backend/app/sql/semantic_validator.py`
9. `backend/app/sql/sandbox.py`
10. `backend/app/agents/tools/sql_tools.py`
11. `backend/app/db_connectors/`
12. `backend/app/api/chat.py`
13. `frontend/src/composables/useSSE.ts`
14. `frontend/src/stores/chat.ts`
15. `frontend/src/components/chat/MessageBubble.vue`

## 23. 演示前检查清单

```bash
git status --short
make test
make lint

cd frontend
npm run type-check
npm run build

cd ../backend
TESTING=1 UV_CACHE_DIR=/tmp/gbase8a-uv-cache uv run python scripts/setup_sqlite_demo.py
```

然后确认：

- `backend/.env` 有可用模型 API Key。
- 前端已选择“SQLite 电商演示库”。
- 后端 `/api/health` 正常。
- “查询2025年销售总额”返回 `57246`。
- “各区域销售额排行”能够生成可信 JOIN。
- “查询销售”不会盲目执行。
- 知识库演示若依赖引用来源，提前启动 Qdrant 或确认本地知识文件存在。
