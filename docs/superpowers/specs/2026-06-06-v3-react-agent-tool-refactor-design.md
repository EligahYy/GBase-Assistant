# V3: True Multi-Agent ReAct + Tool Architecture Refactor

> 2026-06-06 | 设计文档 | 状态: Draft

## 1. 问题诊断

### 1.1 当前 v2 架构的本质

v2 架构名义上是"多 Agent"，但实际上是一个**静态 DAG Pipeline + 局部 LLM 增强**：

| 组件 | v2 实现 | 问题 |
|------|---------|------|
| Orchestrator | `classify_intent_v2()` 关键词 `if/else` | 不能推理，不能动态调整，进入 SQL 分支就"一条路走到黑" |
| Semantic Mapper | `create_react_agent` + 6 tools | **唯一的真正 ReAct Agent** |
| SQL Specialist | `build_sql_prompt()` → LLM 流式 | 只是 prompt 工程，没有 tool |
| SQL Verifier | `validate_sql()` 规则校验 | 纯函数，无 LLM |
| SQL Executor | `SQLSandbox.execute_readonly()` | 纯函数 |
| Knowledge Specialist | `build_qa_prompt()` → LLM 流式 | 只是 prompt 工程，没有 tool |
| General Specialist | `build_general_prompt()` → LLM 流式 | 只是 prompt 工程，没有 tool |
| Response Formatter | 拼装 final_response 字符串 | 格式化逻辑 |

### 1.2 核心痛点

1. **Orchestrator 太傻** — 关键词匹配无法处理歧义、多意图、中途切换
2. **节点太碎** — 10 个硬编码节点把 Agent 内部能力拆成 pipeline 步骤，丧失自主性
3. **Tool 没有标准化** — 6 个 tool 是闭包工厂函数，无 `BaseTool`、无 `ToolRegistry`
4. **State 是扁平 TypedDict** — 24 个字段，Agent 之间通过字典耦合而非消息传递
5. **纠错是图循环** — SQL 校验失败 → 图条件边回退重试 3 次，而非 Agent 自主 observe→diagnose→retry

### 1.3 目标架构原则

- **每个 Agent 是独立的 ReAct 循环**：Think → Act(Tool) → Observe → Decide
- **Tool 是第一公民**：统一的 `BaseTool` 抽象 + `ToolRegistry` 注册中心
- **图退化为轻量编排层**：只负责 Supervisor 调度 + 流式输出，不承载业务逻辑
- **Agent 间通过消息传递**：Supervisor 委托 → Specialist 返回结构化结果

## 2. 目标架构

### 2.1 Agent 拓扑

```
                        ┌─────────────────────┐
                        │    Supervisor Agent  │
                        │    (ReAct + 5 tools) │
                        └──────────┬──────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
     delegate_to_sql      delegate_to_knowledge    respond_general
              │                    │                    │
              ▼                    ▼                    ▼
   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐
   │  SQL Agent      │  │  Knowledge Agent│  │  General Agent  │
   │  (ReAct, 7 tools)│  │  (ReAct, 3 tools)│  │  (chat only)    │
   └─────────────────┘  └─────────────────┘  └─────────────────┘
```

图结构从 **10 节点** 收敛为 **2 个 ReAct SubGraph + 1 个轻量 text node**：

- **SQL Agent SubGraph** — 7 tools 的完整 ReAct 循环
- **Knowledge Agent SubGraph** — 2 tools 的 ReAct 循环
- **General** 不单独成 SubGraph — 它是 Supervisor 的 `respond_general` tool，直接 LLM 生成文本，无需图节点

真正的复杂度在 Agent 内部的 tool-use 循环。

### 2.2 图和 Agent 的关系

LangGraph 的职责退化为：
1. 持有 Supervisor Agent 的 ReAct 循环
2. 在 Supervisor 调用 delegate tool 时，启动对应的 Specialist Agent SubGraph
3. SubGraph 完成后回到 Supervisor（Supervisor 可能多次委托）
4. 收集最终输出，通过 AG-UI SSE 流式转发

```
START → Supervisor Node (ReAct loop, 5 tools)
           │
           ├─ tool_call: delegate_to_sql ──→ SQL Agent SubGraph (ReAct, 7 tools) ──→ back to Supervisor
           ├─ tool_call: delegate_to_knowledge ──→ Knowledge Agent SubGraph (ReAct, 2 tools) ──→ back to Supervisor
           ├─ tool_call: respond_general ──→ 直接 LLM 文本（无 subgraph）
           └─ tool_call: get_database_status ──→ 直接 DB 查询（无 subgraph）
           │
           └─→ Response Formatter → END
```

## 3. Agent 详细设计

### 3.1 Supervisor Agent

**职责**：意图理解、任务委托、兜底处理。是所有用户请求的入口。

**System Prompt 核心约束**：
```
你是 GBase 8a 数据库 AI 助手的主管 Agent。你的职责是理解用户意图并委托给合适的专家 Agent。

## 决策规则
1. 涉及数据查询、SQL 生成、数据库 schema → 委托给 SQL Agent
2. 涉及 GBase 8a 技术知识、错误码、配置 → 委托给 Knowledge Agent
3. 问候、闲聊、超出 GBase 范围 → 直接 respond_general
4. 数据库状态监控 → 直接调用 get_database_status（短路快速通道）
5. 意图不明确 → 用 ask_user_clarification 询问

## 重要原则
- 每次只委托一个 Agent，观察结果后再决定下一步
- 如果 Agent 返回失败/不确定，切换策略而非强行继续
- 保持对话连贯性，记住之前的委托历史
```

**Tools**：

| Tool | 签名 | 说明 |
|------|------|------|
| `delegate_to_sql_specialist` | `(query: str, context: dict) -> dict` | 委托 SQL Agent，返回 `{sql, result, chart_config, error}` |
| `delegate_to_knowledge_specialist` | `(query: str) -> dict` | 委托 Knowledge Agent，返回 `{answer, sources, error}` |
| `respond_general` | `(message: str) -> str` | 直接回复，用于闲聊/引导 |
| `get_database_status` | `() -> dict` | 监控快速通道，短路到系统表查询 |
| `ask_user_clarification` | `(question: str) -> None` | 打断流程，向用户提问 |

**ReAct 循环示例（多意图场景）**：
```
User: "上个月销售额是多少？对了，GBase 8a 支持窗口函数吗？"

Think: 用户有两个独立问题。先处理第一个 SQL 问题。
Act: delegate_to_sql_specialist("上个月销售额")
Obs: {sql: "SELECT SUM(amount)...", result: {rows: [...], row_count: 1}}

Think: SQL 问题已解决。现在处理第二个知识问题。
Act: delegate_to_knowledge_specialist("GBase 8a 是否支持窗口函数")
Obs: {answer: "GBase 8a 支持 ROW_NUMBER, RANK, DENSE_RANK...", sources: [...]}

→ 最终回复包含两部分结果
```

### 3.2 SQL Agent

**职责**：端到端 SQL 生成 + 验证 + 执行 + 自纠错。**合并当前 5 个节点的全部能力**。

**System Prompt 核心约束**：
```
你是 GBase 8a SQL 专家 Agent。你的任务是：理解数据需求 → 探索 Schema → 生成 SQL → 验证 → 执行 → 返回结果。

## 工作流（不是必须线性的，你可以灵活调整）
1. 用 search_schemas 找到相关表
2. 用 get_table_profile 查看列结构
3. 必要时用 query_glossary 查业务术语
4. 多表查询时用 find_join_path 找关联
5. 生成 GBase 8a 兼容 SQL
6. 用 validate_sql 验证语法和 Schema 一致性
7. 用 execute_sql 执行获取结果
8. 如果失败，分析错误并修正（最多 3 轮）

## 方言约束
- 不支持 UPDATE/DELETE/INSERT（只读沙箱）
- 不支持 WINDOW 子句的 RANGE/ROWS 帧
- 不支持 WITH RECURSIVE CTE
- LIMIT 语法: LIMIT n OFFSET m 或 LIMIT m,n
- 字符串连接用 CONCAT()，不用 ||

## 输出
返回结构化 JSON: {sql, result, chart_config, explanation, error}
```

**Tools（7 个）**：

| # | Tool | 来源 | 说明 |
|---|------|------|------|
| 1 | `search_schemas(query)` | semantic_mapper | Qdrant 语义检索相关表 DDL |
| 2 | `get_table_profile(table)` | semantic_mapper | 列名、类型、角色、标签、枚举值、关联关系 |
| 3 | `query_glossary(term)` | semantic_mapper | 业务术语 → 表.列 映射 |
| 4 | `find_join_path(a, b)` | semantic_mapper | BFS JOIN 路径查找 |
| 5 | `validate_sql(sql)` | sql_verifier | 语法+Schema 三层校验 |
| 6 | `execute_sql(sql)` | sql_executor | 沙箱只读执行，返回 rows |
| 7 | `lookup_error(code)` | semantic_mapper | GBase 错误码语义搜索 |

**ReAct 循环示例（自纠错场景）**：
```
Think: 需要查上月各产品销售额
Act: search_schemas("产品销售额")
Obs: 找到 orders, products 表

Think: 看看列结构
Act: get_table_profile("orders")
Act: get_table_profile("products")
Obs: orders.amount (DECIMAL), orders.created_at (DATETIME), products.name (VARCHAR)

Think: 没有直接关联 orders 和 products
Act: find_join_path("orders", "products")
Obs: orders.product_id = products.id

Think: 可以生成 SQL 了
Act: [输出 SQL: SELECT p.name, SUM(o.amount) FROM orders o JOIN products p ON o.product_id = p.id WHERE o.created_at >= DATE_SUB(NOW(), INTERVAL 1 MONTH) GROUP BY p.name]

Think: 验证一下
Act: validate_sql("SELECT p.name, SUM(o.amount)...")
Obs: {valid: false, errors: ["函数 DATE_SUB 需要 2 个参数，GBase 8a 使用 DATE_SUB(date, INTERVAL expr unit)"]}

Think: 修正日期函数语法
Act: [重新生成 SQL: ... WHERE o.created_at >= CURDATE() - INTERVAL 1 MONTH ...]

Think: 再次验证
Act: validate_sql("... CURDATE() - INTERVAL 1 MONTH ...")
Obs: {valid: true}

Think: 执行
Act: execute_sql("SELECT p.name, SUM(o.amount)...")
Obs: {columns: ["name", "total"], rows: [["产品A", 150000], ...], row_count: 5}

→ 返回 {sql: "...", result: {...}, chart_config: {type: "bar", x: "name", y: "total"}}
```

### 3.3 Knowledge Agent

**职责**：GBase 8a 技术知识问答，RAG 增强。

**System Prompt 核心约束**：
```
你是 GBase 8a 知识专家 Agent。回答技术问题时：
1. 先 search_knowledge 检索相关文档
2. 如果检索结果不足以回答问题，尝试用不同关键词再搜
3. 基于检索结果回答，注明来源
4. 遇到错误码问题，用 lookup_error 查询
5. 如果知识库没有答案，诚实说明并给出建议
```

**Tools（3 个）**：

| # | Tool | 说明 |
|---|------|------|
| 1 | `search_knowledge(query)` | 混合检索（Qdrant 语义 + ripgrep 精确） |
| 2 | `lookup_error(code)` | GBase 错误码查询 |
| 3 | `search_gbase_web(query)` | (future) gbase.cn 网页搜索 |

### 3.4 General Agent

**职责**：闲聊兜底 + 用户引导。最小 tool set，纯对话 Agent。

**System Prompt 核心约束**：
```
你是 GBase 8a 数据库助手。你可以进行友好对话。
如果用户的问题涉及数据查询或技术问题，引导他们描述具体需求，
以便 Supervisor 将你重新路由到合适的专家 Agent。
```

无需独立 tool，纯 LLM 生成。

## 4. Tool 标准化设计

### 4.1 目标

当前 6 个 tool 是通过闭包工厂函数创建的无类型函数，没有统一的 schema、验证、注册机制。

### 4.2 Tool Protocol

```python
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

@dataclass
class ToolParameter:
    name: str
    type: str  # "string" | "integer" | "boolean" | "array"
    description: str
    required: bool = True
    enum: list[str] | None = None

@runtime_checkable
class AgentTool(Protocol):
    """标准 Tool 接口。所有 Agent tool 必须实现。"""

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def parameters(self) -> list[ToolParameter]: ...

    async def execute(self, **kwargs) -> Any: ...

    def to_openai_schema(self) -> dict:
        """转换为 OpenAI function calling 格式"""
        ...
```

### 4.3 ToolRegistry

```python
class ToolRegistry:
    """工具注册中心。Agent 按需获取自己的 tool set。"""

    def register(self, tool: AgentTool) -> None: ...
    def get(self, name: str) -> AgentTool | None: ...
    def list_for_agent(self, agent_type: str) -> list[AgentTool]: ...
    def to_openai_tools(self, agent_type: str) -> list[dict]: ...

# 全局单例
_tool_registry = ToolRegistry()
```

### 4.4 迁移映射

| 当前闭包 | 新 Tool 类 | Agent |
|----------|-----------|-------|
| `_make_query_glossary_tool()` | `QueryGlossaryTool` | SQL |
| `_make_search_schema_semantic_tool()` | `SearchSchemasTool` | SQL |
| `_make_get_table_profile_tool()` | `GetTableProfileTool` | SQL |
| `_make_find_join_path_tool()` | `FindJoinPathTool` | SQL |
| `_make_get_database_status_tool()` | `GetDatabaseStatusTool` | Supervisor |
| `_make_query_error_code_tool()` | `LookupErrorCodeTool` | SQL + Knowledge |
| (none) | `ValidateSQLTool` | SQL |
| (none) | `ExecuteSQLTool` | SQL |
| (none) | `SearchKnowledgeTool` | Knowledge |
| (none) | `DelegateToSQLAgent` | Supervisor |
| (none) | `DelegateToKnowledgeAgent` | Supervisor |

## 5. State 重构

### 5.1 当前 State 的问题

24 个扁平字段，所有 Agent 共享同一个 TypedDict。字段虽然标注了"所有权"，但技术上任何节点都能读写任意字段。

### 5.2 新 State 设计

按 Agent 拆分，每个 Agent 有自己的子状态 namespace：

```python
class SupervisorState(TypedDict, total=False):
    """Supervisor 专属状态"""
    intent: str
    delegated_agent: str | None
    delegation_history: list[dict]
    needs_clarification: str | None

class SQLAgentState(TypedDict, total=False):
    """SQL Agent 专属状态"""
    retrieved_schemas: list
    business_terms: dict | None
    generated_sql: str | None
    validation_result: dict | None
    query_result: dict | None
    execution_error: str | None
    chart_config: dict | None
    sql_retry_count: int

class KnowledgeAgentState(TypedDict, total=False):
    """Knowledge Agent 专属状态"""
    retrieved_chunks: list
    knowledge_sources: list[str]

class AgentState(TypedDict, total=False):
    """顶层共享状态"""
    # ── 消息历史（共享） ──
    messages: Annotated[list, add_messages]

    # ── Agent 子状态（隔离） ──
    supervisor: SupervisorState
    sql: SQLAgentState
    knowledge: KnowledgeAgentState

    # ── 输出 ──
    final_response: str | None

    # ── 元数据 ──
    conversation_id: str
    db_connection_id: str | None
    model: str
    history: list[dict]
```

### 5.3 隔离原则

- Supervisor 只写 `state["supervisor"]` 下的字段
- SQL Agent 只写 `state["sql"]` 下的字段
- Knowledge Agent 只写 `state["knowledge"]` 下的字段
- 跨 Agent 通信通过**消息**（Supervisor 的 delegate tool 参数和返回值），而非直接读写对方 state

## 6. 图结构

### 6.1 新图定义（伪代码）

```python
def build_v3_graph() -> StateGraph:
    builder = StateGraph(AgentState)

    # 3 个图节点（替代原来的 10 个）
    builder.add_node("supervisor", supervisor_react_node)
    builder.add_node("sql_agent", sql_agent_subgraph)       # SubGraph: ReAct + 7 tools
    builder.add_node("knowledge_agent", knowledge_agent_subgraph)  # SubGraph: ReAct + 2 tools
    builder.add_node("response_formatter", response_formatter_node)

    builder.add_edge(START, "supervisor")

    # Supervisor ReAct 循环: tool_call → SubGraph / 直接输出 → 回到 Supervisor
    builder.add_conditional_edges("supervisor", route_supervisor_action, {
        "sql_agent": "sql_agent",
        "knowledge_agent": "knowledge_agent",
        "response": "response_formatter",
        "end": END,
    })

    # 子 Agent 完成后回到 Supervisor（可能继续委托其他 Agent 或结束）
    builder.add_edge("sql_agent", "supervisor")
    builder.add_edge("knowledge_agent", "supervisor")

    builder.add_edge("response_formatter", END)

    return builder.compile(checkpointer=MemorySaver())
```

### 6.2 与 v2 图的对比

| 维度 | v2 | v3 |
|------|-----|-----|
| 节点数 | 10 | 4（含 2 个 subgraph） |
| 条件边 | 3 个静态路由函数 | 1 个动态路由（LLM 决策） |
| 循环 | `sql_verifier → sql_specialist`（硬编码最多 3 次） | Agent 内部 ReAct 循环（自主决定） |
| 路由逻辑 | `route_after_intent()`, `route_after_supervisor()`, `route_verifier()` | Supervisor LLM tool_call 决策 |

## 7. 文件结构变化

```
backend/app/agents/
├── state.py              # AgentState + 子 State TypedDict
├── tools/                # 🆕 标准 Tool 目录
│   ├── __init__.py
│   ├── base.py           # AgentTool Protocol + ToolRegistry
│   ├── schema_tools.py   # SearchSchemas, GetTableProfile, FindJoinPath
│   ├── glossary_tool.py  # QueryGlossary
│   ├── sql_tools.py      # ValidateSQL, ExecuteSQL
│   ├── knowledge_tools.py # SearchKnowledge, LookupError
│   └── delegate_tools.py # DelegateToSQLAgent, DelegateToKnowledgeAgent
├── agents/               # 🆕 Agent 实现目录
│   ├── __init__.py
│   ├── supervisor.py     # Supervisor Agent (ReAct)
│   ├── sql_agent.py      # SQL Agent (ReAct)
│   ├── knowledge_agent.py # Knowledge Agent (ReAct)
│   └── general_agent.py  # General Agent (chat)
├── graph.py              # 精简为 Supervisor → SubGraphs → END
├── prompts.py             # Agent system prompts 集中管理
├── schema_graph.py       # 保留，SQL Agent 的 tool 层使用
├── semantic_mapper.py    # 废弃，能力迁移到 SQL Agent tools
└── orchestrator.py       # 废弃，关键字分类逻辑移除
```

## 8. 迁移策略

### Phase 1: Tool 标准化（不改变行为）

1. 定义 `AgentTool` Protocol + `ToolRegistry`
2. 将现有 6 个闭包 tool 改写为标准 Tool 类
3. 保持 `semantic_mapper_node` 不变，只替换 tool 创建方式
4. 验证：163 个现有测试全部通过

### Phase 2: Agent 收敛

1. 实现 `SQLAgent`（ReAct），将 `semantic_mapper` + `sql_specialist` + `sql_verifier` + `sql_executor` 合并
2. 实现 `KnowledgeAgent`（ReAct），替代 `knowledge_specialist`
3. 实现 `SupervisorAgent`（ReAct），替代 `orchestrator` + `supervisor_check`
4. 实现新 `graph.py`（3 节点 + subgraph）
5. 并行运行新旧图，对比输出

### Phase 3: 清理

1. 移除旧节点函数（`orchestrator_node`, `semantic_mapper_node`, `sql_specialist_node`, `sql_verifier_node`, `sql_executor_node`, `knowledge_specialist_node`, `supervisor_check_node`）
2. 移除 `orchestrator.py`
3. 移除 `semantic_mapper.py`
4. 更新 `state.py` 为新结构

## 9. 测试策略

### 新增测试

| 类别 | 内容 |
|------|------|
| Tool 单元测试 | 每个 Tool 类的 schema 输出、execute 行为 |
| ToolRegistry | 注册、查询、按 Agent 过滤 |
| Agent 单元测试 | Mock LLM，验证 ReAct 循环的 tool 选择逻辑 |
| 图集成测试 | 完整流：user msg → supervisor → agent → response |
| 回退测试 | 新旧架构相同输入得到相同输出（或新架构更好） |

### 现有测试

163 个现有测试在迁移期间**必须持续通过**。

## 10. 风险与缓解

| 风险 | 缓解 |
|------|------|
| ReAct 循环失控（无限 tool call） | 设置 `max_iterations=15`，达到上限后强制输出 |
| LLM 路由错误增加延迟 | Supervisor 使用 faster/cheaper 模型（如 qwen-turbo），Specialist 用主模型 |
| Tool 调用增加 token 消耗 | Tool 结果截断（DDL 200 字、检索 top-5 条），System Prompt 精简 |
| 迁移期间功能回退 | Phase 2 双轨并行，feature flag 控制新旧路径 |
