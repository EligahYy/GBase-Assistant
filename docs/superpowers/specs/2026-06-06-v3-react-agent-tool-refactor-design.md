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

## 5. 流式可见性：思考 + Tool 调用全透明

### 5.1 目标体验（参考 Claude Code）

用户应该能看到 Agent 的**完整思考链**：

```
🔍 正在思考...
   用户想查询上个月的销售额，这需要 SQL 查询能力。
   委托给 SQL Agent...

📞 调用工具: delegate_to_sql_specialist
   └─ 参数: {"query": "上个月各产品销售额统计"}

  ┌─ SQL Agent ─────────────────────────────────────┐
  │ 🔍 正在思考...                                    │
  │   首先需要找到存储销售数据的表                      │
  │                                                   │
  │ 📞 调用工具: search_schemas                        │
  │    └─ 参数: {"query": "产品销售额"}                 │
  │    ✅ 返回: 找到 orders, products, order_items      │
  │                                                   │
  │ 🔍 正在思考...                                    │
  │   找到了 3 张相关表，查看列结构确认字段              │
  │                                                   │
  │ 📞 调用工具: get_table_profile                     │
  │    └─ 参数: {"table": "orders"}                   │
  │    ✅ 返回: 12 列 (id, amount, created_at, ...)    │
  │                                                   │
  │ 📞 调用工具: get_table_profile                     │
  │    └─ 参数: {"table": "products"}                 │
  │    ✅ 返回: 8 列 (id, name, category_id, ...)      │
  │                                                   │
  │ 🔍 正在思考...                                    │
  │   信息已足够。需要 JOIN orders 和 products。        │
  │   生成 SQL...                                     │
  │                                                   │
  │ ```sql                                            │
  │ SELECT p.name, SUM(o.amount) AS total             │
  │ FROM orders o                                     │
  │ JOIN products p ON o.product_id = p.id             │
  │ WHERE o.created_at >= CURDATE() - INTERVAL 1 MONTH │
  │ GROUP BY p.name                                   │
  │ ORDER BY total DESC                               │
  │ ```                                               │
  │                                                   │
  │ 🔍 正在思考...                                    │
  │   先验证 SQL 语法和 Schema 一致性                   │
  │                                                   │
  │ 📞 调用工具: validate_sql                          │
  │    └─ 参数: {"sql": "SELECT p.name..."}            │
  │    ✅ 返回: {valid: true}                          │
  │                                                   │
  │ 📞 调用工具: execute_sql                           │
  │    └─ 参数: {"sql": "SELECT p.name..."}            │
  │    ✅ 返回: 5 行, 耗时 42ms                         │
  └──────────────────────────────────────────────────┘

🔍 正在思考...
   SQL Agent 已完成查询，整理结果...

📊 查询结果: 5 行
📈 图表配置: 柱状图
```

### 5.2 AG-UI 事件扩展

当前 `EventEncoder` 已支持 `TOOL_CALL_START` / `TOOL_CALL_RESULT` / `TOOL_CALL_END`，但缺少 **思考过程** 和 **步骤边界** 事件。

#### 新增事件类型

```python
class EventType(StrEnum):
    # ── 现有 ──
    TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
    TOOL_CALL_START = "TOOL_CALL_START"
    TOOL_CALL_RESULT = "TOOL_CALL_RESULT"
    TOOL_CALL_END = "TOOL_CALL_END"
    STATE_DELTA = "STATE_DELTA"
    RUN_STARTED = "RUN_STARTED"
    RUN_FINISHED = "RUN_FINISHED"
    RUN_ERROR = "RUN_ERROR"

    # ── 🆕 思考可见性 ──
    THINKING_START = "THINKING_START"       # 开始思考（前端展示折叠区）
    THINKING_CONTENT = "THINKING_CONTENT"   # 思考内容 delta 流式
    THINKING_END = "THINKING_END"           # 思考结束

    # ── 🆕 步骤生命周期 ──
    STEP_STARTED = "STEP_STARTED"           # Agent 步骤开始（标注是哪个 Agent）
    STEP_FINISHED = "STEP_FINISHED"         # Agent 步骤结束
```

#### EventEncoder 新增方法

```python
@staticmethod
def thinking_start() -> str:
    return EventEncoder._encode(EventType.THINKING_START)

@staticmethod
def thinking_delta(delta: str) -> str:
    return EventEncoder._encode(EventType.THINKING_CONTENT, delta=delta)

@staticmethod
def thinking_end() -> str:
    return EventEncoder._encode(EventType.THINKING_END)

@staticmethod
def step_started(agent_name: str, step_index: int = 0) -> str:
    return EventEncoder._encode(
        EventType.STEP_STARTED,
        agent_name=agent_name,
        step_index=step_index,
    )

@staticmethod
def step_finished(agent_name: str) -> str:
    return EventEncoder._encode(
        EventType.STEP_FINISHED,
        agent_name=agent_name,
    )
```

### 5.3 ReAct 循环中的事件发射

每个 Agent 的 ReAct 循环需要在关键节点发射事件。关键切入点：**通过 LangGraph 的 `get_stream_writer()` 在 tool 执行前后发射事件**。

#### 方案：自定义 ReAct Agent（替代 `create_react_agent`）

`langgraph.prebuilt.create_react_agent` 是一个黑盒 — 它的内部 tool 调用和推理过程无法插入自定义事件。需要替换为**自定义 ReAct 图**：

```python
def build_react_agent(
    model: BaseChatModel,
    tools: list[AgentTool],
    system_prompt: str,
    agent_name: str,
    max_iterations: int = 15,
) -> StateGraph:
    """构建自定义 ReAct Agent 子图，在 tool 调用和推理过程中发射流式事件。"""

    builder = StateGraph(ReActState)

    builder.add_node("agent", _react_agent_node(model, tools, system_prompt))
    builder.add_node("tools", _tool_execution_node(tools, agent_name))

    builder.add_edge(START, "agent")

    # Agent 节点输出 → 路由: 有 tool_call → 执行 tools, 否则 → END
    builder.add_conditional_edges("agent", _route_after_agent, {
        "tools": "tools",
        "end": END,
    })

    # tools 节点执行完毕后回到 agent（ReAct 循环）
    builder.add_edge("tools", "agent")

    return builder.compile()
```

#### Agent 节点：发射 THINKING 事件

```python
async def _react_agent_node(model, tools, system_prompt):
    """ReAct Agent 推理节点 — 流式发射 THINKING 事件。"""

    async def node_fn(state: ReActState) -> dict:
        writer = get_stream_writer()

        # 🆕 发射 STEP_STARTED（仅首次）
        if state.get("step_index", 0) == 0:
            writer([{"step_started": {"agent_name": agent_name}}])

        messages = state["messages"]

        # 流式调用 LLM，将推理过程作为 THINKING 事件发射
        thinking_buffer = ""
        async for token in model.astream(messages):
            thinking_buffer += token

            # 🆕 发射 THINKING_CONTENT delta
            writer([{"thinking_delta": token}])

        # 解析 LLM 输出中的 tool_call 或 text response
        last_msg = ...  # 从 LLM 输出中提取

        if has_tool_calls(last_msg):
            return {"messages": [last_msg], "step_index": state.get("step_index", 0) + 1}
        else:
            # 最终文本输出
            if last_msg.content:
                writer([{"delta": last_msg.content}])
            return {"messages": [last_msg], "finished": True}

    return node_fn
```

#### Tools 节点：发射 TOOL_CALL 事件

```python
async def _tool_execution_node(tools: list[AgentTool], agent_name: str):
    """执行 tool 并发射 TOOL_CALL_START / TOOL_CALL_RESULT / TOOL_CALL_END 事件。"""

    async def node_fn(state: ReActState) -> dict:
        writer = get_stream_writer()
        last_msg = state["messages"][-1]
        tool_calls = last_msg.tool_calls  # 从 AI 消息中提取

        tool_messages = []
        for tc in tool_calls:
            tool_name = tc["name"]
            tool_args = tc["args"]

            # 🆕 发射 TOOL_CALL_START
            writer([{
                "tool_call_start": {
                    "name": tool_name,
                    "args": tool_args,
                    "agent_name": agent_name,
                }
            }])

            # 执行 tool
            tool = tool_registry.get(tool_name)
            try:
                result = await tool.execute(**tool_args)
                result_str = tool.format_result(result)  # 截断/格式化

                # 🆕 发射 TOOL_CALL_RESULT
                writer([{
                    "tool_call_result": {
                        "name": tool_name,
                        "result": result_str,
                    }
                }])
            except Exception as e:
                writer([{
                    "tool_call_result": {
                        "name": tool_name,
                        "error": str(e),
                    }
                }])

            # 🆕 发射 TOOL_CALL_END
            writer([{"tool_call_end": {"name": tool_name}}])

            tool_messages.append(ToolMessage(content=result_str, tool_call_id=tc["id"]))

        return {"messages": tool_messages}

    return node_fn
```

### 5.4 图层的流式适配

Supervisor 的 `graph.py` 需要处理两类流事件：

```python
async def run_agent_with_ag_ui(user_message, conversation_id, model, db_connection_id):
    ...
    async for mode, events in graph.astream(initial_state, config=config, stream_mode=["custom", "updates"]):
        if mode == "custom":
            for ev in events:
                if isinstance(ev, dict):
                    # ── 🆕 思考事件 ──
                    if "thinking_delta" in ev:
                        yield EventEncoder.thinking_delta(ev["thinking_delta"])

                    # ── 🆕 步骤事件 ──
                    elif "step_started" in ev:
                        info = ev["step_started"]
                        yield EventEncoder.step_started(info["agent_name"])

                    # ── 🆕 Tool 调用事件 ──
                    elif "tool_call_start" in ev:
                        info = ev["tool_call_start"]
                        yield EventEncoder.tool_call_start(info["name"], info.get("args"))

                    elif "tool_call_result" in ev:
                        info = ev["tool_call_result"]
                        yield EventEncoder.tool_call_result(info["name"], info.get("result", {}))

                    elif "tool_call_end" in ev:
                        yield EventEncoder.tool_call_end(ev["tool_call_end"]["name"])

                    # ── 现有事件 ──
                    elif "delta" in ev:
                        yield EventEncoder.text_delta(ev["delta"])
                    elif "sql" in ev:
                        yield EventEncoder.sql_event(ev["sql"])
                    elif "chart_config" in ev:
                        yield EventEncoder.chart_config(ev["chart_config"])
                    elif "result" in ev:
                        yield EventEncoder.result_event(ev["result"])
    ...
```

### 5.5 前端适配

#### useSSE.ts — 新增事件处理

```typescript
export interface SSEChunk {
  type: 'text' | 'sql' | 'sources' | 'warning' | 'done' | 'error'
    | 'result' | 'result_error' | 'message_ids'
    | 'TEXT_MESSAGE_CONTENT' | 'STATE_DELTA' | 'chart_config'
    // 🆕
    | 'THINKING_START' | 'THINKING_CONTENT' | 'THINKING_END'
    | 'TOOL_CALL_START' | 'TOOL_CALL_RESULT' | 'TOOL_CALL_END'
    | 'STEP_STARTED' | 'STEP_FINISHED'
  delta?: string
  tool_name?: string
  agent_name?: string
  args?: Record<string, unknown>
  result?: Record<string, unknown>
  step_index?: number
  // ...
}
```

#### Chat Store — 新增状态管理

```typescript
// 流式消息中可追加的中间状态
interface StreamingState {
  // 思考内容（折叠区内）
  thinking: string          // 当前思考文本
  isThinking: boolean       // 是否正在思考

  // Tool 调用历史
  toolCalls: ToolCallEntry[]

  // 当前活跃的 Agent
  activeAgent: string | null
  agentStepIndex: number
}

interface ToolCallEntry {
  id: string
  name: string
  args: Record<string, unknown>
  result?: string
  error?: string
  status: 'pending' | 'running' | 'done' | 'error'
  agentName: string
}
```

#### MessageBubble.vue — 思考 + Tool 可见渲染

在每条 AI 消息气泡内，渲染：

1. **思考折叠区**（`THINKING_CONTENT`）
   - 默认折叠，用灰色斜体显示
   - 流式过程中自动展开
   - 标题："🔍 思考中..." → "💭 思考过程"（完成后）

2. **Tool 调用卡片**（`TOOL_CALL_START` / `TOOL_CALL_RESULT`）
   - 紧凑卡片：图标 + tool name + 参数摘要
   - 状态指示：🔄 执行中 / ✅ 完成 / ❌ 失败
   - 点击展开查看完整参数和返回值

3. **Agent 切换指示**（`STEP_STARTED`）
   - "🤖 SQL Agent 正在处理..." / "📚 Knowledge Agent 检索中..."
   - 缩进层级表示嵌套关系

```
┌─ AI Message ─────────────────────────────────────┐
│                                                   │
│  💭 思考过程                          [展开/折叠]  │
│  ┌─────────────────────────────────────────────┐ │
│  │ 用户想查询上个月的销售额，需要 SQL...         │ │
│  │ 委托给 SQL Agent...                          │ │
│  └─────────────────────────────────────────────┘ │
│                                                   │
│  🤖 SQL Agent 处理中                             │
│  ┌─────────────────────────────────────────────┐ │
│  │ 💭 思考...    首先需要找到销售相关的表        │ │
│  │                                              │ │
│  │ 📞 search_schemas              ✅ 完成       │ │
│  │    参数: {"query": "产品销售额"}              │ │
│  │    结果: 找到 orders, products                │ │
│  │                                              │ │
│  │ 📞 get_table_profile            ✅ 完成       │ │
│  │    参数: {"table": "orders"}                 │ │
│  │    结果: 12 列                              │ │
│  │                                              │ │
│  │ 💭 思考...    信息足够，开始生成 SQL          │ │
│  │                                              │ │
│  │ 📞 validate_sql                 ✅ 通过       │ │
│  │ 📞 execute_sql                  ✅ 5行, 42ms  │ │
│  └─────────────────────────────────────────────┘ │
│                                                   │
│  ```sql                                          │
│  SELECT p.name, SUM(o.amount) AS total           │
│  FROM orders o                                   │
│  JOIN products p ON o.product_id = p.id           │
│  ...                                             │
│  ```                                             │
│                                                   │
│  📊 查询结果: 5 行                                │
│  ┌──────────┬──────────┐                        │
│  │ name     │ total    │                        │
│  ├──────────┼──────────┤                        │
│  │ 产品A    │ 150,000  │                        │
│  │ 产品B    │ 120,000  │                        │
│  └──────────┴──────────┘                        │
└───────────────────────────────────────────────────┘
```

### 5.6 流式事件时序

完整时序（SQL 查询场景）：

```
Time ──────────────────────────────────────────────────────────→

RUN_STARTED
│
├─ STEP_STARTED {agent: "supervisor"}
│   THINKING_START
│   THINKING_CONTENT: "这是数据查询..." (delta 流式)
│   THINKING_END
│   TOOL_CALL_START {name: "delegate_to_sql_specialist"}
│   TOOL_CALL_END {name: "delegate_to_sql_specialist"}
│   │
│   ├─ STEP_STARTED {agent: "sql_agent"}   ← 嵌套在 SQL SubGraph 内
│   │   THINKING_START
│   │   THINKING_CONTENT: "先找相关表..."
│   │   THINKING_END
│   │   TOOL_CALL_START {name: "search_schemas"}
│   │   TOOL_CALL_RESULT {name: "search_schemas", result: {...}}
│   │   TOOL_CALL_END {name: "search_schemas"}
│   │   ... (更多 tool 调用)
│   │   TEXT_MESSAGE_CONTENT: "```sql\nSELECT ...\n```"
│   │   STATE_DELTA {path: "sql"}
│   │   STATE_DELTA {path: "result"}
│   │   STATE_DELTA {path: "chart_config"}
│   ├─ STEP_FINISHED {agent: "sql_agent"}
│   │
│   TOOL_CALL_RESULT {name: "delegate_to_sql_specialist"}
│   THINKING_START
│   THINKING_CONTENT: "整理结果..."
│   THINKING_END
├─ STEP_FINISHED {agent: "supervisor"}
│
TEXT_MESSAGE_CONTENT: "查询完成，共 5 条记录..."
RUN_FINISHED
```

### 5.7 Tool 结果格式化

为避免 SSE 传输超大 payload，Tool 结果需要在服务端截断/格式化：

```python
class AgentTool(Protocol):
    # ...

    def format_result(self, result: Any) -> dict:
        """将 tool 执行结果格式化为前端可展示的结构。

        Returns:
            {
                "summary": "找到 3 张表: orders, products, order_items",
                "detail": {...},  # 可选，完整数据供前端展开
                "truncated": bool,
            }
        """
        ...

# 各 Tool 的格式化规则
TOOL_RESULT_FORMAT = {
    "search_schemas": lambda r: {
        "summary": f"找到 {len(r)} 张表: {', '.join(t.table_name for t in r[:5])}",
        "detail": [{"table": t.table_name, "description": t.description} for t in r[:5]],
        "truncated": len(r) > 5,
    },
    "get_table_profile": lambda r: {
        "summary": f"{r['table_name']}: {len(r['columns'])} 列",
        "detail": r,
    },
    "execute_sql": lambda r: {
        "summary": f"{r['row_count']} 行, {r['execution_time_ms']}ms",
        "detail": {"columns": r["columns"], "rows": r["rows"][:20]},
        "truncated": r.get("truncated", False),
    },
    "validate_sql": lambda r: {
        "summary": "✅ 验证通过" if r["valid"] else f"❌ {len(r['errors'])} 个错误",
        "detail": r,
    },
}
```

## 6. State 重构

### 6.1 当前 State 的问题

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

## 7. 图结构

### 7.1 新图定义（伪代码）

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

### 7.2 与 v2 图的对比

| 维度 | v2 | v3 |
|------|-----|-----|
| 节点数 | 10 | 4（含 2 个 subgraph） |
| 条件边 | 3 个静态路由函数 | 1 个动态路由（LLM 决策） |
| 循环 | `sql_verifier → sql_specialist`（硬编码最多 3 次） | Agent 内部 ReAct 循环（自主决定） |
| 路由逻辑 | `route_after_intent()`, `route_after_supervisor()`, `route_verifier()` | Supervisor LLM tool_call 决策 |

## 8. 文件结构变化

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

## 9. 迁移策略

### Phase 1: Tool 标准化 + 流式事件（不改变行为）

1. 定义 `AgentTool` Protocol + `ToolRegistry` + `format_result()` 接口
2. 将现有 6 个闭包 tool 改写为标准 Tool 类
3. 新增 AG-UI 事件类型：`THINKING_START/CONTENT/END`、`STEP_STARTED/FINISHED`
4. 新增 `EventEncoder` 对应编码方法
5. 前端 `useSSE.ts` 新增事件类型定义
6. 保持现有图节点不变，只替换 tool 创建方式
7. 验证：163 个现有测试全部通过

### Phase 2: Agent 收敛 + 自定义 ReAct 图

1. 实现自定义 `build_react_agent()`（替代 `create_react_agent`），在 tool 调用前后发射流式事件
2. 实现 `SQLAgent`（ReAct + 7 tools），合并 5 个节点
3. 实现 `KnowledgeAgent`（ReAct + 2 tools）
4. 实现 `SupervisorAgent`（ReAct + 5 tools）
5. 实现新 `graph.py`（Supervisor + 2 SubGraph）
6. 前端 `MessageBubble` 新增思考折叠区 + Tool 调用卡片渲染
7. 并行运行新旧图，对比输出

### Phase 3: 清理

1. 移除旧节点函数（`orchestrator_node`, `semantic_mapper_node`, `sql_specialist_node`, `sql_verifier_node`, `sql_executor_node`, `knowledge_specialist_node`, `supervisor_check_node`）
2. 移除 `orchestrator.py`
3. 移除 `semantic_mapper.py`
4. 更新 `state.py` 为新结构

## 10. 测试策略

### 新增测试

| 类别 | 内容 |
|------|------|
| Tool 单元测试 | 每个 Tool 类的 schema 输出、execute 行为、format_result |
| ToolRegistry | 注册、查询、按 Agent 过滤 |
| 流式事件测试 | EventEncoder 新增事件类型编码、SSE 格式校验 |
| Agent 单元测试 | Mock LLM，验证 ReAct 循环的 tool 选择逻辑 + 事件发射 |
| 图集成测试 | 完整流：user msg → supervisor → agent → response + 事件序列验证 |
| 前端渲染测试 | THINKING 折叠区、TOOL_CALL 卡片、STEP 嵌套渲染 |
| 回退测试 | 新旧架构相同输入得到相同输出（或新架构更好） |

### 现有测试

163 个现有测试在迁移期间**必须持续通过**。

## 11. 风险与缓解

| 风险 | 缓解 |
|------|------|
| ReAct 循环失控（无限 tool call） | 设置 `max_iterations=15`，达到上限后强制输出 |
| LLM 路由错误增加延迟 | Supervisor 使用 faster/cheaper 模型（如 qwen-turbo），Specialist 用主模型 |
| Tool 调用增加 token 消耗 | Tool 结果截断（`format_result`），System Prompt 精简 |
| 迁移期间功能回退 | Phase 2 双轨并行，feature flag 控制新旧路径 |
| 流式事件量过大导致前端卡顿 | 前端批量渲染（60ms buffer），思考内容默认折叠，Tool 结果摘要优先 |
| `create_react_agent` 替换后 Agent 行为退化 | 自定义 ReAct 图在 tool 选择和推理质量上做 A/B 对比，低于阈值则回退 |
| 嵌套 SubGraph 事件顺序错乱 | 事件携带 `agent_name` + `step_index`，前端按层级重组而非依赖时序 |
