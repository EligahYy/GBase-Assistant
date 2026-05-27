# Phase 1: 基础设施 + AG-UI Gateway Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 搭建 LangGraph 多 Agent 编排基础设施 + AG-UI 标准化事件协议 Gateway，v2 与 v1 并存不破坏现有功能。

**Architecture:** 新增 `backend/app/agents/` (AgentState + Orchestrator + Graph) 和 `backend/app/gateway/` (EventEncoder)，新增 `/api/v2/chat/stream` 端点使用 LangGraph + AG-UI 事件，前端新增 `useAGUIClient` 适配器。v1 `/api/chat/stream` 保持不变。

**Tech Stack:** LangGraph, FastAPI SSE, Vue 3 Composition API, Python 3.12+

---

## 文件结构

| 文件 | 职责 | 操作 |
|------|------|------|
| `backend/app/agents/__init__.py` | 包入口 | 新建 |
| `backend/app/agents/state.py` | AgentState TypedDict 定义 | 新建 |
| `backend/app/agents/orchestrator.py` | Orchestrator 意图分类+路由 | 新建 |
| `backend/app/agents/graph.py` | LangGraph 图构建+运行 | 新建 |
| `backend/app/gateway/__init__.py` | 包入口 | 新建 |
| `backend/app/gateway/ag_ui_encoder.py` | AG-UI 事件编码器 | 新建 |
| `backend/app/api/chat_v2.py` | v2 聊天 API (AG-UI SSE) | 新建 |
| `backend/app/main.py` | 挂载 v2 路由 | 修改 |
| `frontend/src/composables/useAGUIClient.ts` | Vue AG-UI 客户端适配器 | 新建 |
| `backend/tests/test_agents/__init__.py` | 测试包入口 | 新建 |
| `backend/tests/test_agents/test_state.py` | AgentState 测试 | 新建 |
| `backend/tests/test_agents/test_orchestrator.py` | Orchestrator 路由测试 | 新建 |
| `backend/tests/test_gateway/__init__.py` | 测试包入口 | 新建 |
| `backend/tests/test_gateway/test_ag_ui_encoder.py` | EventEncoder 测试 | 新建 |
| `backend/tests/test_api_v2.py` | v2 API 集成测试 | 新建 |

---

### Task 1: 安装 LangGraph 依赖 + 创建目录结构

**Files:**
- Modify: `backend/requirements.txt` — 添加 `langgraph` 依赖
- Create: `backend/app/agents/__init__.py`
- Create: `backend/app/gateway/__init__.py`
- Create: `backend/tests/test_agents/__init__.py`
- Create: `backend/tests/test_gateway/__init__.py`

- [ ] **Step 1: 添加 langgraph 到 requirements.txt**

Read `backend/requirements.txt` first. Add `langgraph>=0.2.0` on a new line at the end.

- [ ] **Step 2: 安装依赖**

```bash
cd backend && .venv/bin/pip install langgraph>=0.2.0
```

Expected: `Successfully installed langgraph-0.2.x`

- [ ] **Step 3: 创建目录和 `__init__.py` 文件**

```bash
mkdir -p backend/app/agents backend/app/gateway backend/tests/test_agents backend/tests/test_gateway
touch backend/app/agents/__init__.py
touch backend/app/gateway/__init__.py
touch backend/tests/test_agents/__init__.py
touch backend/tests/test_gateway/__init__.py
```

- [ ] **Step 4: Commit**

```bash
git add backend/requirements.txt backend/app/agents/ backend/app/gateway/ backend/tests/test_agents/ backend/tests/test_gateway/
git commit -m "chore: add langgraph dependency, create agents and gateway packages"
```

---

### Task 2: AgentState 定义

**Files:**
- Create: `backend/app/agents/state.py`
- Create: `backend/tests/test_agents/test_state.py`

- [ ] **Step 1: 编写测试**

Create `backend/tests/test_agents/test_state.py`:

```python
"""AgentState 单元测试。"""

from app.agents.state import AgentState


class TestAgentState:
    def test_minimal_state_creation(self):
        """AgentState 应能用最小字段创建。"""
        state: AgentState = {
            "messages": [],
            "conversation_id": "test-conv-1",
            "model": "deepseek/deepseek-chat",
        }
        assert state["conversation_id"] == "test-conv-1"
        assert state["model"] == "deepseek/deepseek-chat"
        assert state["messages"] == []

    def test_sql_path_state(self):
        """SQL 路径相关字段应可设置。"""
        state: AgentState = {
            "messages": [{"role": "user", "content": "查询订单"}],
            "intent": "sql",
            "db_connection_id": "conn-1",
            "conversation_id": "test-conv-2",
            "model": "deepseek/deepseek-chat",
        }
        assert state["intent"] == "sql"
        assert state["db_connection_id"] == "conn-1"
        assert state.get("grounding") is None
        assert state.get("generated_sql") is None

    def test_grounding_fields(self):
        """Grounding 相关字段应独立存在。"""
        grounding = {
            "tables": ["order_main", "product"],
            "columns": {"order_main": ["order_amount", "order_time"], "product": ["name"]},
            "join_paths": ["order_main.product_code = product.product_code"],
            "confidence": 0.92,
        }
        state: AgentState = {
            "messages": [],
            "intent": "sql",
            "grounding": grounding,
            "conversation_id": "c1",
            "model": "m1",
        }
        assert state["grounding"]["tables"] == ["order_main", "product"]
        assert state["grounding"]["confidence"] == 0.92

    def test_fields_have_no_defaults_for_optional(self):
        """total=False 意味着所有字段可选，未设置时 get 返回 None。"""
        state: AgentState = {
            "messages": [],
            "conversation_id": "c1",
            "model": "m1",
        }
        assert state.get("intent") is None
        assert state.get("generated_sql") is None
        assert state.get("query_result") is None
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd backend && .venv/bin/python -m pytest tests/test_agents/test_state.py -v
```

Expected: FAIL — `ModuleNotFoundError: No module named 'app.agents.state'`

- [ ] **Step 3: 实现 AgentState**

Create `backend/app/agents/state.py`:

```python
"""AgentState — LangGraph 共享状态定义。"""

from typing import Annotated, Literal

from langgraph.graph.message import add_messages


class AgentState(dict):
    """多 Agent 共享状态。

    使用 total=False 的 TypedDict 语义：所有字段可选，Agent 只读写自己的字段。
    实际实现为 dict 子类以兼容 LangGraph StateGraph。
    """

    # LangGraph 使用 Annotated 类型来定义 state schema
    # 由于 Python 的 TypedDict 在 LangGraph 中有兼容性限制，
    # 我们通过 StateGraph 的 schema 参数显式定义
    pass


# LangGraph StateGraph 使用的 state schema
# 不使用 TypedDict 继承，直接定义 __annotations__
def create_agent_state_schema() -> type:
    """返回用于 LangGraph StateGraph 的 state 类型。"""
    from typing import TypedDict

    class _AgentState(TypedDict, total=False):
        # ── 消息历史（跨 Agent 共享，只增不减） ──
        messages: Annotated[list, add_messages]

        # ── Orchestrator 专属 ──
        intent: Literal["sql", "qa", "general", "clarify"]
        task_dag: list[dict]
        current_task: str

        # ── Schema Grounding 专属（Phase 3 才实际使用） ──
        grounding: dict | None
        needs_clarification: str | None
        grounding_retry_count: int

        # ── SQL Specialist 专属（Phase 3 才实际使用） ──
        generated_sql: str | None
        sql_retry_count: int

        # ── SQL Verifier 专属（Phase 3 才实际使用） ──
        validation_errors: list[str]
        validation_passed: bool

        # ── SQL Executor 专属（Phase 3 才实际使用） ──
        query_result: dict | None
        execution_error: str | None

        # ── Knowledge Specialist 专属（Phase 3 才实际使用） ──
        retrieved_docs: list[dict]
        knowledge_sources: list[str]

        # ── 输出 ──
        final_response: str | None
        confidence_score: int
        assumptions: list[str]

        # ── 元数据 ──
        conversation_id: str
        db_connection_id: str | None
        model: str

    return _AgentState


AgentStateType = create_agent_state_schema()
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd backend && .venv/bin/python -m pytest tests/test_agents/test_state.py -v
```

Expected: 4 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/state.py backend/tests/test_agents/test_state.py
git commit -m "feat: add AgentState definition for multi-agent shared state"
```

---

### Task 3: AG-UI EventEncoder

**Files:**
- Create: `backend/app/gateway/ag_ui_encoder.py`
- Create: `backend/tests/test_gateway/test_ag_ui_encoder.py`

- [ ] **Step 1: 编写测试**

Create `backend/tests/test_gateway/test_ag_ui_encoder.py`:

```python
"""EventEncoder 单元测试。"""

import json

from app.gateway.ag_ui_encoder import EventEncoder


class TestEventEncoder:
    def test_run_started(self):
        result = EventEncoder.run_started("conv-1")
        assert result.startswith("data: ")
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "RUN_STARTED"
        assert payload["conversation_id"] == "conv-1"

    def test_text_delta(self):
        result = EventEncoder.text_delta("Hello")
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "TEXT_MESSAGE_CONTENT"
        assert payload["delta"] == "Hello"

    def test_tool_call_start(self):
        result = EventEncoder.tool_call_start("schema_grounding", {"query": "test"})
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "TOOL_CALL_START"
        assert payload["tool_name"] == "schema_grounding"
        assert payload["args"] == {"query": "test"}

    def test_tool_call_start_default_args(self):
        """未传 args 时应为 {}。"""
        result = EventEncoder.tool_call_start("sql_generator")
        payload = json.loads(result[6:].strip())
        assert payload["args"] == {}

    def test_tool_call_end(self):
        result = EventEncoder.tool_call_end("sql_generator")
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "TOOL_CALL_END"
        assert payload["tool_name"] == "sql_generator"

    def test_tool_call_result(self):
        result = EventEncoder.tool_call_result("sql_executor", {"rows": 5, "time_ms": 120})
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "TOOL_CALL_RESULT"
        assert payload["result"]["rows"] == 5

    def test_state_delta(self):
        result = EventEncoder.state_delta("/grounding", {"tables": ["orders"]})
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "STATE_DELTA"
        assert payload["path"] == "/grounding"
        assert payload["value"]["tables"] == ["orders"]

    def test_run_finished(self):
        result = EventEncoder.run_finished()
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "RUN_FINISHED"

    def test_run_error(self):
        result = EventEncoder.run_error("Something went wrong")
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "RUN_ERROR"
        assert payload["message"] == "Something went wrong"

    def test_sse_format(self):
        """所有事件必须符合 SSE 标准：data: {json}\\n\\n"""
        result = EventEncoder.text_delta("x")
        assert result.endswith("\n\n")
        # 不应有多余换行
        assert result.count("\n") == 2

    def test_json_escape(self):
        """特殊字符应在 JSON 中正确转义。"""
        result = EventEncoder.text_delta('line1\nline2\t"quoted"')
        payload = json.loads(result[6:].strip())
        assert payload["delta"] == 'line1\nline2\t"quoted"'

    def test_all_events_end_with_double_newline(self):
        """所有事件类型都必须以 \\n\\n 结尾。"""
        events = [
            EventEncoder.run_started("c1"),
            EventEncoder.text_delta("x"),
            EventEncoder.tool_call_start("t"),
            EventEncoder.tool_call_end("t"),
            EventEncoder.tool_call_result("t", {}),
            EventEncoder.state_delta("/p", {}),
            EventEncoder.run_finished(),
            EventEncoder.run_error("e"),
        ]
        for event in events:
            assert event.endswith("\n\n"), f"Event {event[:50]} does not end with \\n\\n"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd backend && .venv/bin/python -m pytest tests/test_gateway/test_ag_ui_encoder.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 EventEncoder**

Create `backend/app/gateway/ag_ui_encoder.py`:

```python
"""AG-UI 事件编码器。将 Agent 输出转为标准 SSE 事件。"""

from __future__ import annotations

import json
from enum import StrEnum


class EventType(StrEnum):
    TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
    TOOL_CALL_START = "TOOL_CALL_START"
    TOOL_CALL_RESULT = "TOOL_CALL_RESULT"
    TOOL_CALL_END = "TOOL_CALL_END"
    STATE_DELTA = "STATE_DELTA"
    RUN_STARTED = "RUN_STARTED"
    RUN_FINISHED = "RUN_FINISHED"
    RUN_ERROR = "RUN_ERROR"


class EventEncoder:
    """将 LangGraph Agent 输出编码为 AG-UI 标准 SSE 事件字符串。

    每个编码方法返回一个可直接写入 SSE 流的完整行：
        data: {"type":"...","key":"value",...}\\n\\n

    所有公共方法都是 @staticmethod，无需实例化。
    """

    @staticmethod
    def _encode(event_type: EventType, **kwargs: object) -> str:
        payload: dict[str, object] = {"type": event_type.value}
        payload.update(kwargs)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def run_started(conversation_id: str) -> str:
        return EventEncoder._encode(
            EventType.RUN_STARTED, conversation_id=conversation_id
        )

    @staticmethod
    def text_delta(content: str) -> str:
        return EventEncoder._encode(EventType.TEXT_MESSAGE_CONTENT, delta=content)

    @staticmethod
    def tool_call_start(tool_name: str, args: dict | None = None) -> str:
        return EventEncoder._encode(
            EventType.TOOL_CALL_START, tool_name=tool_name, args=args or {}
        )

    @staticmethod
    def tool_call_end(tool_name: str) -> str:
        return EventEncoder._encode(EventType.TOOL_CALL_END, tool_name=tool_name)

    @staticmethod
    def tool_call_result(tool_name: str, result: dict) -> str:
        return EventEncoder._encode(
            EventType.TOOL_CALL_RESULT, tool_name=tool_name, result=result
        )

    @staticmethod
    def state_delta(path: str, value: dict) -> str:
        return EventEncoder._encode(EventType.STATE_DELTA, path=path, value=value)

    @staticmethod
    def run_finished() -> str:
        return EventEncoder._encode(EventType.RUN_FINISHED)

    @staticmethod
    def run_error(message: str) -> str:
        return EventEncoder._encode(EventType.RUN_ERROR, message=message)
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd backend && .venv/bin/python -m pytest tests/test_gateway/test_ag_ui_encoder.py -v
```

Expected: 11 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/gateway/ag_ui_encoder.py backend/tests/test_gateway/test_ag_ui_encoder.py
git commit -m "feat: add AG-UI EventEncoder for standardized SSE event output"
```

---

### Task 4: Orchestrator Agent（意图分类 + 路由）

**Files:**
- Create: `backend/app/agents/orchestrator.py`
- Create: `backend/tests/test_agents/test_orchestrator.py`

- [ ] **Step 1: 编写测试**

Create `backend/tests/test_agents/test_orchestrator.py`:

```python
"""Orchestrator Agent 单元测试。"""

import pytest
from app.agents.state import AgentStateType
from app.agents.orchestrator import classify_intent_v2, route_after_intent


class TestClassifyIntentV2:
    def test_sql_keywords_map_to_sql_intent(self):
        """包含查询关键词的文本应映射为 sql intent。"""
        assert classify_intent_v2("查询所有订单") == "sql"
        assert classify_intent_v2("统计上个月的销售额") == "sql"
        assert classify_intent_v2("列出最近30天的数据") == "sql"
        assert classify_intent_v2("分析各部门绩效") == "sql"

    def test_qa_keywords_map_to_qa_intent(self):
        """包含知识问答关键词的文本应映射为 qa intent。"""
        assert classify_intent_v2("GBase 8a 支持窗口函数吗") == "qa"
        assert classify_intent_v2("怎么创建分布表") == "qa"
        assert classify_intent_v2("错误码 1001 是什么意思") == "qa"

    def test_general_fallback(self):
        """无特殊关键词的文本应映射为 general intent。"""
        assert classify_intent_v2("你好") == "general"
        assert classify_intent_v2("今天天气怎么样") == "general"
        assert classify_intent_v2("你能做什么") == "general"

    def test_mixed_keywords_prioritize_sql(self):
        """同时包含 SQL 和 QA 关键词时，SQL 优先（因为包含具体数据查询意图）。"""
        # "查询" 触发 sql，"怎么" 触发 qa，"查询" 优先
        assert classify_intent_v2("查询怎么建表") == "sql"


class TestRouteAfterIntent:
    def test_sql_intent_routes_to_schema_grounding(self):
        state: AgentStateType = {
            "messages": [],
            "intent": "sql",
            "conversation_id": "c1",
            "model": "m1",
        }
        assert route_after_intent(state) == "schema_grounding"

    def test_qa_intent_routes_to_knowledge_specialist(self):
        state: AgentStateType = {
            "messages": [],
            "intent": "qa",
            "conversation_id": "c1",
            "model": "m1",
        }
        assert route_after_intent(state) == "knowledge_specialist"

    def test_general_intent_routes_to_general_specialist(self):
        state: AgentStateType = {
            "messages": [],
            "intent": "general",
            "conversation_id": "c1",
            "model": "m1",
        }
        assert route_after_intent(state) == "general_specialist"

    def test_clarify_intent_routes_to_response_formatter(self):
        state: AgentStateType = {
            "messages": [],
            "intent": "clarify",
            "conversation_id": "c1",
            "model": "m1",
        }
        assert route_after_intent(state) == "response_formatter"

    def test_missing_intent_defaults_to_general(self):
        """未设置 intent 时应默认 general。"""
        state: AgentStateType = {
            "messages": [],
            "conversation_id": "c1",
            "model": "m1",
        }
        assert route_after_intent(state) == "general_specialist"
```

- [ ] **Step 2: 运行测试验证失败**

```bash
cd backend && .venv/bin/python -m pytest tests/test_agents/test_orchestrator.py -v
```

Expected: FAIL — `ModuleNotFoundError`

- [ ] **Step 3: 实现 Orchestrator**

Create `backend/app/agents/orchestrator.py`:

```python
"""Orchestrator Agent — 意图分类与路由决策。

Phase 1 使用基于关键词的简易意图分类。Phase 3 将升级为 LLM-based 分类。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agents.state import AgentStateType

logger = logging.getLogger(__name__)

# ── 关键词分类规则 ──
_SQL_KEYWORDS = (
    "查询", "统计", "列出", "分析", "计算", "汇总",
    "SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY",
    "select", "from", "where",
)
_QA_KEYWORDS = (
    "支持", "怎么", "如何", "什么", "为什么", "错误",
    "参数", "配置", "版本", "语法",
)


def classify_intent_v2(user_message: str) -> str:
    """基于关键词的意图分类。返回 "sql" | "qa" | "general"。

    Phase 1 使用关键词规则，Phase 3 升级为 LLM-based。
    """
    for kw in _SQL_KEYWORDS:
        if kw in user_message:
            return "sql"
    for kw in _QA_KEYWORDS:
        if kw in user_message:
            return "qa"
    return "general"


def route_after_intent(state: AgentStateType) -> str:
    """根据 intent 路由到对应 Specialist。

    Orchestrator ReAct 循环的 Act 步骤。Phase 1 中 Specialist 节点为 stub，
    Phase 3 接入真实 Agent。
    """
    intent = state.get("intent") or "general"
    routing_map = {
        "sql": "schema_grounding",
        "qa": "knowledge_specialist",
        "general": "general_specialist",
        "clarify": "response_formatter",
    }
    target = routing_map.get(intent, "general_specialist")
    logger.info("Orchestrator: intent=%s → %s", intent, target)
    return target
```

- [ ] **Step 4: 运行测试验证通过**

```bash
cd backend && .venv/bin/python -m pytest tests/test_agents/test_orchestrator.py -v
```

Expected: 8 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/orchestrator.py backend/tests/test_agents/test_orchestrator.py
git commit -m "feat: add Orchestrator agent with keyword-based intent classification and routing"
```

---

### Task 5: LangGraph 图构建 + Stub Specialist 节点

**Files:**
- Create: `backend/app/agents/graph.py`

- [ ] **Step 1: 实现图构建函数**

Create `backend/app/agents/graph.py`:

```python
"""LangGraph 图构建和运行。

Phase 1 搭建完整图结构，Specialist 节点为 stub 实现。
Phase 3 中每个 stub 将被替换为真实 Agent。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.agents.orchestrator import classify_intent_v2, route_after_intent
from app.agents.state import AgentStateType
from app.gateway.ag_ui_encoder import EventEncoder

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ── Phase 1 Stub 节点 ──
# 这些节点在 Phase 1 只输出 AG-UI 事件和基础响应。
# Phase 3 将替换为真实的 LLM Agent 调用。

async def orchestrator_node(state: AgentStateType) -> dict:
    """Orchestrator: 分类意图，记录到 state。"""
    user_msg = ""
    msgs = state.get("messages", [])
    if msgs:
        last = msgs[-1]
        if isinstance(last, dict):
            user_msg = last.get("content", "")
    intent = classify_intent_v2(user_msg)
    state["intent"] = intent
    return {"intent": intent}


async def schema_grounding_node(state: AgentStateType) -> dict:
    """Schema Grounding stub: Phase 3 实现。"""
    return {"grounding": None}


async def sql_specialist_node(state: AgentStateType) -> dict:
    """SQL Specialist stub: Phase 3 实现。"""
    return {"generated_sql": None, "final_response": "SQL 生成功能将在 Phase 3 实现。"}


async def sql_verifier_node(state: AgentStateType) -> dict:
    """SQL Verifier stub: Phase 3 实现。"""
    return {"validation_passed": True}


async def sql_executor_node(state: AgentStateType) -> dict:
    """SQL Executor stub: Phase 3 实现。"""
    return {"query_result": None}


async def knowledge_specialist_node(state: AgentStateType) -> dict:
    """Knowledge Specialist stub: Phase 3 实现。"""
    return {"final_response": "知识问答功能将在 Phase 3 实现。"}


async def general_specialist_node(state: AgentStateType) -> dict:
    """General Specialist stub: Phase 3 实现。"""
    return {"final_response": "您好！我是 GBase 8a 助手。SQL 生成和知识问答功能将在后续版本中上线。"}


async def response_formatter_node(state: AgentStateType) -> dict:
    """Response Formatting: 汇聚最终响应。"""
    return {}


# ── 图构建 ──

def build_graph() -> StateGraph:
    """构建 LangGraph StateGraph。

    Phase 1: 完整图结构，stub 节点。Phase 3: 替换 stub。
    """
    builder = StateGraph(AgentStateType)

    # 注册所有节点
    builder.add_node("orchestrator", orchestrator_node)
    builder.add_node("schema_grounding", schema_grounding_node)
    builder.add_node("sql_specialist", sql_specialist_node)
    builder.add_node("sql_verifier", sql_verifier_node)
    builder.add_node("sql_executor", sql_executor_node)
    builder.add_node("knowledge_specialist", knowledge_specialist_node)
    builder.add_node("general_specialist", general_specialist_node)
    builder.add_node("response_formatter", response_formatter_node)

    # 入口
    builder.add_edge(START, "orchestrator")

    # Orchestrator 条件路由
    builder.add_conditional_edges("orchestrator", route_after_intent, {
        "schema_grounding": "schema_grounding",
        "knowledge_specialist": "knowledge_specialist",
        "general_specialist": "general_specialist",
        "response_formatter": "response_formatter",
    })

    # SQL 路径: grounding → specialist → verifier → executor → response
    builder.add_edge("schema_grounding", "sql_specialist")
    builder.add_edge("sql_specialist", "sql_verifier")

    # Verifier 条件路由
    def route_verifier(state: AgentStateType) -> str:
        if state.get("validation_passed"):
            return "sql_executor"
        retry = state.get("sql_retry_count", 0)
        if retry < 3:
            state["sql_retry_count"] = retry + 1
            return "sql_specialist"
        return "response_formatter"

    builder.add_conditional_edges("sql_verifier", route_verifier, {
        "sql_executor": "sql_executor",
        "sql_specialist": "sql_specialist",
        "response_formatter": "response_formatter",
    })

    builder.add_edge("sql_executor", "response_formatter")

    # 其他路径 → response
    builder.add_edge("knowledge_specialist", "response_formatter")
    builder.add_edge("general_specialist", "response_formatter")

    # 结束
    builder.add_edge("response_formatter", END)

    return builder.compile(checkpointer=MemorySaver())


# ── Agent Runner（AG-UI 事件流） ──

async def run_agent_with_ag_ui(
    user_message: str,
    conversation_id: str,
    model: str,
    db_connection_id: str | None = None,
) -> AsyncIterator[str]:
    """运行 LangGraph Agent 并以 AG-UI 事件流输出。

    供 chat_v2 API 端点调用。每个图节点执行后检查 state，
    将变更编码为对应 AG-UI 事件。

    Args:
        user_message: 用户输入文本
        conversation_id: 会话 ID
        model: LLM 模型标识
        db_connection_id: 数据库连接 ID（可选）

    Yields:
        SSE 格式的 AG-UI 事件字符串
    """
    graph = build_graph()

    initial_state: AgentStateType = {
        "messages": [{"role": "user", "content": user_message}],
        "conversation_id": conversation_id,
        "model": model,
        "db_connection_id": db_connection_id,
    }

    # RUN_STARTED
    yield EventEncoder.run_started(conversation_id)

    try:
        # 使用 astream_events 获取节点级别的执行流
        prev_node = None
        async for event in graph.astream_events(initial_state, version="v2"):
            kind = event.get("event", "")
            node_name = event.get("name", "")

            if kind == "on_chain_start" and node_name in (
                "schema_grounding", "sql_specialist", "sql_verifier",
                "sql_executor", "knowledge_specialist", "general_specialist",
            ):
                yield EventEncoder.tool_call_start(node_name)
                prev_node = node_name

            elif kind == "on_chain_end" and node_name == prev_node:
                yield EventEncoder.tool_call_end(node_name)
                prev_node = None

        # 获取最终状态
        final_state = await graph.ainvoke(initial_state)
        response = final_state.get("final_response", "")
        if response:
            yield EventEncoder.text_delta(response)

        # RUN_FINISHED
        yield EventEncoder.run_finished()

    except Exception as e:
        logger.error("Agent run failed: %s", e)
        yield EventEncoder.run_error(str(e))
```

- [ ] **Step 2: 验证导入无错误**

```bash
cd backend && .venv/bin/python -c "from app.agents.graph import build_graph, run_agent_with_ag_ui; print('OK')"
```

Expected: `OK`

- [ ] **Step 3: 验证图可以运行（集成测试）**

```bash
cd backend && .venv/bin/python -c "
import asyncio
from app.agents.graph import run_agent_with_ag_ui
async def test():
    events = []
    async for e in run_agent_with_ag_ui('你好', 'test-1', 'test-model'):
        events.append(e)
    print(f'Received {len(events)} events')
    # 第一个事件应为 RUN_STARTED
    assert 'RUN_STARTED' in events[0], f'First event: {events[0][:80]}'
    # 最后一个有意义的事件应为 RUN_FINISHED
    assert 'RUN_FINISHED' in events[-2] or 'RUN_FINISHED' in events[-1], f'Last events: {events[-2:]}'
    print('All checks passed')
asyncio.run(test())
"
```

Expected: 输出 "All checks passed"

- [ ] **Step 4: Commit**

```bash
git add backend/app/agents/graph.py
git commit -m "feat: add LangGraph graph builder with stub specialist nodes and AG-UI agent runner"
```

---

### Task 6: v2 Chat API 端点

**Files:**
- Create: `backend/app/api/chat_v2.py`

- [ ] **Step 1: 实现 v2 端点**

Create `backend/app/api/chat_v2.py`:

```python
"""v2 Chat API — LangGraph 多 Agent + AG-UI 事件流。

与 v1 /api/chat/stream 并存，不破坏现有功能。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse

from app.agents.graph import run_agent_with_ag_ui
from app.schemas.chat import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/chat", tags=["chat-v2"])

# E402 — FastAPI StreamingResponse 放在文件末尾，前面的 import 没问题


@router.post("/stream")
async def chat_stream_v2(request: ChatRequest = Body(...)):
    """v2 流式聊天接口 — AG-UI 标准 SSE 事件流。

    复用 v1 的 ChatRequest schema，输出升级为 AG-UI 事件类型。
    """
    conversation_id = request.conversation_id or ""

    event_stream = run_agent_with_ag_ui(
        user_message=request.message,
        conversation_id=conversation_id,
        model=request.model or "deepseek/deepseek-chat",
        db_connection_id=request.db_connection_id,
    )

    return StreamingResponse(
        event_stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Conversation-Id": conversation_id,
        },
    )
```

- [ ] **Step 2: 挂载 v2 路由到 FastAPI**

Read `backend/app/main.py`. Find the line:
```python
app.include_router(api_router)
```

After it, add:
```python
from app.api.chat_v2 import router as chat_v2_router
app.include_router(chat_v2_router, prefix="/api")
```

- [ ] **Step 3: 编写集成测试**

Create `backend/tests/test_api_v2.py`:

```python
"""v2 Chat API 集成测试。"""

import json
import pytest
from httpx import AsyncClient, ASGITransport
from app.main import app


@pytest.mark.asyncio
async def test_v2_chat_stream_responds_ag_ui_events():
    """v2 端点应返回 AG-UI 标准事件。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v2/chat/stream",
            json={"message": "你好", "model": "deepseek/deepseek-chat"},
            headers={"Accept": "text/event-stream"},
            timeout=10,
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        body = response.text

        # 至少应有 RUN_STARTED 和 RUN_FINISHED
        assert "RUN_STARTED" in body, f"Missing RUN_STARTED in: {body[:200]}"
        assert "RUN_FINISHED" in body, f"Missing RUN_FINISHED in: {body[:200]}"


@pytest.mark.asyncio
async def test_v2_chat_sql_intent():
    """SQL 意图应触发 Schema Grounding 和 SQL Specialist 流程。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v2/chat/stream",
            json={"message": "查询所有订单", "model": "deepseek/deepseek-chat"},
            headers={"Accept": "text/event-stream"},
            timeout=10,
        )
        body = response.text

        # SQL 意图应触发 TOOL_CALL_START
        assert "TOOL_CALL_START" in body, f"Missing TOOL_CALL_START in SQL path: {body[:300]}"


@pytest.mark.asyncio
async def test_v2_chat_general_intent():
    """通用意图应直接路由到 General Specialist。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/v2/chat/stream",
            json={"message": "你好", "model": "deepseek/deepseek-chat"},
            headers={"Accept": "text/event-stream"},
            timeout=10,
        )
        body = response.text

        # General 意图也应触发 TOOL_CALL_START (general_specialist)
        assert "general_specialist" in body, f"Missing general_specialist: {body[:300]}"
```

- [ ] **Step 4: 运行集成测试**

```bash
cd backend && TESTING=1 .venv/bin/python -m pytest tests/test_api_v2.py -v
```

Expected: 3 PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/chat_v2.py backend/app/main.py backend/tests/test_api_v2.py
git commit -m "feat: add v2 chat API endpoint with AG-UI SSE event streaming"
```

---

### Task 7: Vue 3 AG-UI 客户端适配器

**Files:**
- Create: `frontend/src/composables/useAGUIClient.ts`

- [ ] **Step 1: 实现适配器**

Create `frontend/src/composables/useAGUIClient.ts`:

```typescript
import { reactive } from 'vue'

type AgentStatus = 'idle' | 'running' | 'done' | 'error'

interface ToolState {
  name: string
  status: 'pending' | 'running' | 'done' | 'error'
  result?: unknown
}

interface AGUIClientState {
  status: AgentStatus
  currentTool: ToolState | null
  toolHistory: ToolState[]
  stateDeltas: Record<string, unknown>
  error: string | null
  confidence: number | null
  assumptions: string[]
}

export function useAGUIClient() {
  const state = reactive<AGUIClientState>({
    status: 'idle',
    currentTool: null,
    toolHistory: [],
    stateDeltas: {},
    error: null,
    confidence: null,
    assumptions: [],
  })

  let abortController: AbortController | null = null

  async function runAgent(input: string, dbConnectionId?: string, model?: string) {
    state.status = 'running'
    state.toolHistory = []
    state.error = null
    state.confidence = null
    state.assumptions = []

    abortController = new AbortController()
    const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'

    const response = await fetch(`${baseUrl}/v2/chat/stream`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json', Accept: 'text/event-stream' },
      body: JSON.stringify({
        message: input,
        db_connection_id: dbConnectionId || undefined,
        model: model || undefined,
      }),
      signal: abortController.signal,
    })

    if (!response.ok) {
      state.status = 'error'
      state.error = `HTTP ${response.status}`
      return
    }

    const reader = response.body!.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() ?? ''

      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        const json = line.slice(6).trim()
        if (!json) continue
        try {
          const event = JSON.parse(json)
          handleEvent(event)
        } catch { /* ignore malformed JSON */ }
      }
    }
  }

  function handleEvent(event: Record<string, unknown>) {
    switch (event.type) {
      case 'RUN_STARTED':
        state.status = 'running'
        break
      case 'TOOL_CALL_START':
        state.currentTool = {
          name: (event.tool_name as string) || 'unknown',
          status: 'running',
        }
        break
      case 'TOOL_CALL_END':
        if (state.currentTool) {
          state.currentTool.status = 'done'
          state.toolHistory.push({ ...state.currentTool })
          state.currentTool = null
        }
        break
      case 'TOOL_CALL_RESULT':
        if (state.currentTool) {
          state.currentTool.result = event.result
        }
        break
      case 'STATE_DELTA':
        state.stateDeltas[event.path as string] = event.value
        if (event.path === '/output') {
          const output = event.value as Record<string, unknown> | undefined
          state.confidence = (output?.confidence as number) ?? null
          state.assumptions = (output?.assumptions as string[]) ?? []
        }
        break
      case 'RUN_FINISHED':
        state.status = 'done'
        break
      case 'RUN_ERROR':
        state.status = 'error'
        state.error = (event.message as string) || 'Unknown error'
        break
    }
  }

  function cancel() {
    abortController?.abort()
    // Attempt to notify server
    const baseUrl = import.meta.env.VITE_API_BASE_URL || 'http://localhost:8000/api'
    fetch(`${baseUrl}/v2/chat/cancel`, { method: 'POST' }).catch(() => {})
  }

  return { state, runAgent, cancel }
}
```

- [ ] **Step 2: TypeScript 类型检查**

```bash
cd frontend && npx vue-tsc --noEmit 2>&1 | head -20
```

Expected: 无错误（或仅有预存的无关错误）

- [ ] **Step 3: Commit**

```bash
git add frontend/src/composables/useAGUIClient.ts
git commit -m "feat: add Vue 3 AG-UI client adapter for standardized SSE event handling"
```

---

### Task 8: 端到端验证 + 目录重构收尾

- [ ] **Step 1: 运行全部后端测试**

```bash
cd backend && TESTING=1 .venv/bin/python -m pytest tests/ -v 2>&1 | tail -40
```

Expected: 所有测试通过（约 130+ PASS），无失败。

- [ ] **Step 2: 运行前端类型检查**

```bash
cd frontend && npx vue-tsc --noEmit
```

Expected: 退出码 0，无类型错误。

- [ ] **Step 3: 验证 v1 和 v2 端点并存**

```bash
cd backend && .venv/bin/python -c "
from app.main import app
routes = [r.path for r in app.routes if hasattr(r, 'path')]
assert '/api/chat/stream' in routes, 'v1 /api/chat/stream missing'
assert '/api/v2/chat/stream' in routes, 'v2 /api/v2/chat/stream missing'
print('Both v1 and v2 endpoints are registered')
"
```

Expected: `Both v1 and v2 endpoints are registered`

- [ ] **Step 4: Commit**

```bash
git add -A
git commit -m "chore: end-to-end verification for Phase 1 infrastructure and AG-UI gateway"
```

---

## Phase 1 完成状态

完成后，系统具备：
- LangGraph 编排框架就绪，8 个节点（1 Orchestrator + 7 Specialist stub）
- AG-UI 标准化事件流：`RUN_STARTED` → `TOOL_CALL_START/END` → `TEXT_MESSAGE_CONTENT` → `RUN_FINISHED`
- v2 `/api/v2/chat/stream` 与 v1 `/api/chat/stream` 并存
- Vue 3 `useAGUIClient` 适配器就绪，等待接入 UI 组件
- Specialist 节点为 stub 实现（返回占位消息），Phase 3 替换为真实 Agent
