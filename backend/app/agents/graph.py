"""LangGraph v3.3 — Three-Phase Circuit Breaker ReAct Agent.

Phases:
  1. explore_agent ⇄ explore_tools  — schema discovery
  2. sql_agent ⇄ submit_sql         — SQL gen + retry
  3. answer_agent → final_answer    — mandatory termination

Circuit breaker rules are graph-level (deterministic), not Prompt-based.
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langgraph.graph import END, START, StateGraph

from app.agents.agents.unified_agent import (
    ANSWER_AGENT_PROMPT,
    EXPLORE_AGENT_PROMPT,
    SQL_AGENT_PROMPT,
    get_answer_tools,
    get_explore_tools,
    get_sql_tools,
)
from app.agents.state import AgentState
from app.gateway.ag_ui_encoder import EventEncoder
from app.llm.adapter import LiteLLMChatAdapter

logger = logging.getLogger(__name__)

# ── Circuit breaker constants ──
MAX_EXPLORE_STEPS = 5
MAX_SCHEMA_EMPTY_SEARCHES = 3
MAX_SQL_RETRIES = 3       # Failed submit_sql retries
MAX_SQL_CALLS = 8         # Total submit_sql calls (exploration + final)
MAX_TOTAL_STEPS = 15
MAX_EMPTY_RESPONSES = 2
MAX_SAME_TOOL_CALLS = 2

# ── Step-level warning thresholds (only injection that remains) ──
MILD_WARNING_AT = 10
URGENT_WARNING_AT = 13


# ═══════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════

def _emit(key: str, value: Any) -> None:
    try:
        get_stream_writer()([{key: value}])
    except RuntimeError:
        pass


def _parse_tool_calls(msg) -> tuple[list[dict] | None, str | None]:
    tool_calls = None
    text = None
    if hasattr(msg, "tool_calls") and msg.tool_calls:
        tool_calls = []
        for tc in msg.tool_calls:
            tool_calls.append({"id": tc.get("id", f"call_{len(tool_calls)}"), "name": tc.get("name", ""), "args": tc.get("args", {})})
    if hasattr(msg, "content") and msg.content:
        content = msg.content
        if isinstance(content, str) and content.strip():
            text = content.strip()
        elif isinstance(content, list):
            parts = []
            for block in content:
                if isinstance(block, dict) and block.get("type") == "text":
                    parts.append(str(block.get("text", "")))
                elif isinstance(block, str):
                    parts.append(block)
            joined = "".join(parts).strip()
            if joined:
                text = joined
    return tool_calls, text


async def _call_llm(model: Any, messages: list[BaseMessage], tool_schemas: list[dict] | None) -> AIMessage:
    if hasattr(model, "_agenerate"):
        kwargs: dict = {}
        if tool_schemas:
            kwargs["tools"] = tool_schemas
        result = await model._agenerate(messages, **kwargs)
        if result.generations and result.generations[0]:
            return result.generations[0].message
        return AIMessage(content="")
    else:
        dict_msgs = []
        for m in messages:
            role = "system" if isinstance(m, SystemMessage) else "user"
            if hasattr(m, "type"):
                role = "assistant" if m.type == "ai" else ("system" if m.type == "system" else "user")
            dict_msgs.append({"role": role, "content": str(m.content)})
        content, _, tool_calls_data = await model.llm_client.complete(dict_msgs, tools=tool_schemas if tool_schemas else None)
        return _make_ai_message(content or "", tool_calls_data)


def _make_ai_message(content: str, tool_calls_data: list[dict] | None = None) -> AIMessage:
    if tool_calls_data:
        from langchain_core.messages import ToolCall as LCToolCall
        lc = [LCToolCall(name=t["name"], args=t.get("args", {}), id=t.get("id", f"call_{i}")) for i, t in enumerate(tool_calls_data)]
        return AIMessage(content=content, tool_calls=lc)
    return AIMessage(content=content)


def _to_openai_tools(tools: list[Any]) -> list[dict]:
    return [t.to_openai_schema() for t in tools if hasattr(t, "to_openai_schema")]


def _build_messages(system_prompt: str, state_msgs: list) -> list[BaseMessage]:
    return [SystemMessage(content=system_prompt)] + list(state_msgs)


def _build_conversation_messages(history: list[dict], current_message: str) -> list[BaseMessage]:
    messages: list[BaseMessage] = []
    for item in history:
        content = str(item.get("content", "")).strip()
        if not content:
            continue
        role = item.get("role")
        messages.append(AIMessage(content=content) if role == "assistant" else HumanMessage(content=content))
    if not messages or not isinstance(messages[-1], HumanMessage) or messages[-1].content != current_message:
        messages.append(HumanMessage(content=current_message))
    return messages


def _thinking_summary(tool_names: list[str]) -> str:
    TOOL_THINKING = {
        "search_schemas": "搜索相关数据库表", "get_table_profile": "查看表字段详情",
        "find_join_path": "查找表关联关系", "query_glossary": "查询业务术语映射",
        "submit_sql": "执行 SQL 查询", "search_knowledge": "检索 GBase 8a 知识库",
        "get_database_status": "获取数据库运行状态", "final_answer": "整理最终回答",
    }
    actions = [TOOL_THINKING.get(n, n) for n in tool_names]
    return actions[0] if len(actions) == 1 else "、".join(actions)


# ═══════════════════════════════════════════════════════════════════════════════
# Circuit Breaker (graph-level, deterministic)
# ═══════════════════════════════════════════════════════════════════════════════

def _cb_init() -> dict:
    """Initialize CB state for a new run."""
    return {
        "explore": {"tables_found": [], "schema_search_count": 0, "last_search_empty": False, "steps": 0},
        "sql": {"generated_sql": None, "status": None, "errors": [], "retry_count": 0, "last_result": None},
        "total_steps": 0, "empty_response_count": 0,
        "last_tool_name": None, "last_tool_args": None, "same_tool_count": 0,
        "current_phase": "explore", "cb_reason": None,
    }


def _cb_update(cb: dict, tool_name: str | None = None, tool_args: dict | None = None) -> dict:
    """Update CB counters after each step. Mutates and returns cb."""
    cb["total_steps"] = cb.get("total_steps", 0) + 1

    if tool_name:
        args_str = json.dumps(tool_args or {}, ensure_ascii=False, sort_keys=True)[:80]
        if cb.get("last_tool_name") == tool_name and cb.get("last_tool_args") == args_str:
            cb["same_tool_count"] = cb.get("same_tool_count", 0) + 1
        else:
            cb["same_tool_count"] = 1
        cb["last_tool_name"] = tool_name
        cb["last_tool_args"] = args_str
    else:
        cb["same_tool_count"] = 0
        cb["last_tool_name"] = None
        cb["last_tool_args"] = None

    return cb


def _cb_explore_update(cb: dict, tool_name: str, result: Any) -> dict:
    """Update explore-specific CB counters. Mutates and returns cb."""
    explore = {**cb.get("explore", {})}
    explore["steps"] = explore.get("steps", 0) + 1

    if tool_name == "search_schemas":
        explore["schema_search_count"] = explore.get("schema_search_count", 0) + 1
        explore["last_search_empty"] = not bool(result)
        if result:
            tables = [getattr(r, "table_name", str(r)) for r in (result if isinstance(result, list) else [result])]
            explore["tables_found"] = list(dict.fromkeys(explore.get("tables_found", []) + tables))[:20]

    cb["explore"] = explore
    return cb


def _cb_sql_update(cb: dict, result: dict) -> dict:
    """Update SQL-specific CB counters from submit_sql result. Mutates and returns cb."""
    sql_state = {**cb.get("sql", {})}

    # Track ALL submit_sql calls (exploration + final + retries)
    sql_state["total_calls"] = sql_state.get("total_calls", 0) + 1

    if isinstance(result, dict):
        sql_state["status"] = result.get("status", "execution_failed")
        sql_state["generated_sql"] = result.get("sql", sql_state.get("generated_sql"))
        if sql_state["status"] == "completed":
            sql_state["last_result"] = result
            # Keep retry_count unchanged on success
        else:
            sql_state["retry_count"] = sql_state.get("retry_count", 0) + 1
            errors = sql_state.get("errors", [])
            error_msg = result.get("error", "") or ";".join(result.get("errors", []))
            if error_msg and error_msg not in errors:
                errors.append(error_msg)
            sql_state["errors"] = errors

    cb["sql"] = sql_state
    return cb


def _cb_check(state: dict, phase: str) -> str | None:
    """Check circuit breaker rules. Returns cb_reason string or None if OK."""
    cb = state.get("cb", {})
    explore = cb.get("explore", {})
    sql = cb.get("sql", {})

    # ── Global ──
    if cb.get("total_steps", 0) >= MAX_TOTAL_STEPS:
        return "total_steps_exceeded"
    if cb.get("empty_response_count", 0) >= MAX_EMPTY_RESPONSES:
        return "empty_response"
    if cb.get("same_tool_count", 0) >= MAX_SAME_TOOL_CALLS:
        return "duplicate_tool"

    # ── Explore phase ──
    if phase == "explore":
        if explore.get("steps", 0) >= MAX_EXPLORE_STEPS:
            return "explore_max_steps"
        if explore.get("schema_search_count", 0) >= MAX_SCHEMA_EMPTY_SEARCHES and explore.get("last_search_empty"):
            return "search_exhausted"

    # ── SQL phase ──
    if phase == "sql":
        if sql.get("retry_count", 0) >= MAX_SQL_RETRIES:
            return "sql_max_retries"
        if sql.get("total_calls", 0) >= MAX_SQL_CALLS:
            return "sql_max_calls"

    return None


def _cb_degradation_message(state: dict) -> str:
    """Build graceful degradation message based on cb_reason."""
    cb = state.get("cb", {})
    reason = cb.get("cb_reason", "unknown")
    explore = cb.get("explore", {})
    sql = cb.get("sql", {})

    if reason == "total_steps_exceeded":
        tables = ", ".join(explore.get("tables_found", []) or ["无"])
        return f"处理步骤达到上限。已识别的表: {tables}。如需更完整的结果，请尝试缩小查询范围。"
    if reason == "search_exhausted":
        tables = ", ".join(explore.get("tables_found", []) or ["无"])
        return f"已尝试多种关键词搜索数据库 Schema，未找到完全匹配的表。已识别的相关表: {tables}。"
    if reason == "explore_max_steps":
        tables = ", ".join(explore.get("tables_found", []) or ["无"])
        return f"探索阶段达到上限。已识别的表: {tables}。建议提供更具体的查询条件。"
    if reason == "sql_max_retries":
        errors = sql.get("errors", [])
        last_sql = sql.get("generated_sql", "")
        err_str = "；".join(errors[-3:]) if errors else "未知错误"
        return f"SQL 经过 3 次尝试仍然失败。错误: {err_str}\n最后生成的 SQL:\n```sql\n{last_sql}\n```"
    if reason == "empty_response":
        return "处理完成。以下是已获取的信息。如有其他问题，请继续提问。"
    if reason == "duplicate_tool":
        return "检测到重复的工具调用，已安全停止。请尝试不同的方式描述您的问题。"
    # normal
    return ""


# ═══════════════════════════════════════════════════════════════════════════════
# Agent node factory
# ═══════════════════════════════════════════════════════════════════════════════

def _make_agent_node(model: Any, get_tools, get_prompt, phase: str):
    """Create a single-pass ReAct agent node for one phase."""

    async def node_fn(state: AgentState) -> dict:
        tools = get_tools()
        system_prompt = get_prompt()
        cb = state.get("cb", _cb_init())
        step_idx = cb.get("total_steps", 0)

        # ── Step-level warnings (only Prompt injection retained) ──
        msgs = list(state.get("messages", []))
        if step_idx == MILD_WARNING_AT:
            msgs.append(HumanMessage(content="系统提示：已执行多轮操作，请尽快给出结果。"))
        elif step_idx == URGENT_WARNING_AT:
            msgs.append(HumanMessage(content="系统提示：即将达到处理上限，请立即基于已有信息输出。"))

        # ── Build degradation context for answer phase ──
        if phase == "answer":
            reason = cb.get("cb_reason", "normal")
            if reason and reason != "normal":
                degradation_msg = _cb_degradation_message(state)
                system_prompt += f"\n\n## 中断原因: {reason}\n{degradation_msg}\n\n请基于以上信息调用 final_answer 输出最好的回答。"

        if step_idx == 0:
            _emit("step_started", {"agent_name": f"{phase}_agent", "phase": phase})

        messages = _build_messages(system_prompt, msgs)
        tool_schemas = _to_openai_tools(tools)

        try:
            response = await _call_llm(model, messages, tool_schemas if tool_schemas else None)
        except Exception as e:
            logger.error("Agent %s LLM call failed: %s", phase, e)
            _emit("delta", f"\n处理出错: {e}")
            return {"cb": _cb_init(), "messages": [AIMessage(content=f"处理出错: {e}")]}

        tool_calls, text = _parse_tool_calls(response)

        # ── final_answer → emit delta, finish ──
        if tool_calls and any(tc["name"] == "final_answer" for tc in tool_calls):
            fa_tc = next(tc for tc in tool_calls if tc["name"] == "final_answer")
            answer = fa_tc.get("args", {}).get("answer", "")
            if answer:
                _emit("delta", answer)
            if text:
                _emit("thinking_start", {})
                _emit("thinking_delta", text)
                _emit("thinking_end", {})
            _emit("thinking_start", {})
            _emit("thinking_delta", "整理最终回答")
            _emit("thinking_end", {})
            _emit("step_finished", {"agent_name": f"{phase}_agent", "phase": phase})
            cb_done = {**cb}
            # Don't overwrite CB reason if circuit breaker already set one
            if not cb_done.get("cb_reason"):
                cb_done["cb_reason"] = "normal"
            return {"cb": cb_done, "final_response": answer, "messages": [response]}

        # ── No tool calls: advance phase (fallback) ──
        if not tool_calls:
            if text:
                _emit("delta", text)
            _emit("step_finished", {"agent_name": f"{phase}_agent", "phase": phase})
            cb_next = _cb_update({**cb}, None, None)
            cb_next["current_phase"] = _next_phase(phase)
            return {"cb": cb_next, "messages": [response]}

        # ── Has tool calls → emit thinking, route to tools ──
        if text:
            _emit("thinking_start", {})
            _emit("thinking_delta", text)
            _emit("thinking_end", {})
        _emit("thinking_start", {})
        _emit("thinking_delta", _thinking_summary([tc["name"] for tc in tool_calls]))
        _emit("thinking_end", {})

        return {"messages": [response]}

    return node_fn


def _next_phase(current: str) -> str:
    return {"explore": "sql", "sql": "answer", "answer": "answer"}.get(current, "explore")


# ═══════════════════════════════════════════════════════════════════════════════
# Tools node
# ═══════════════════════════════════════════════════════════════════════════════

def _make_tools_node(tools: list[Any], phase: str):
    """Execute tool calls, emit events, update CB state."""

    tool_map = {t.name: t for t in tools if hasattr(t, "name")}

    async def node_fn(state: AgentState) -> dict:
        msgs = state.get("messages", [])
        if not msgs:
            return {"messages": []}
        last_msg = msgs[-1]
        tool_calls, _ = _parse_tool_calls(last_msg)
        if not tool_calls:
            return {"messages": []}

        cb = {**state.get("cb", _cb_init())}
        tool_messages = []
        explore_update = cb.get("explore", {})
        sql_update = cb.get("sql", {})

        for tc in tool_calls:
            tool_name = tc["name"]
            tool_args = tc.get("args", {})
            _emit("tool_call_start", {"name": tool_name, "args": tool_args, "agent_name": f"{phase}_agent"})

            tool = tool_map.get(tool_name)
            if tool is None:
                _emit("tool_call_result", {"name": tool_name, "error": f"Tool '{tool_name}' not found"})
                _emit("tool_call_end", {"name": tool_name})
                tool_messages.append(ToolMessage(content=json.dumps({"error": f"Tool '{tool_name}' not found"}), tool_call_id=tc["id"]))
                continue

            try:
                result = await tool.execute(**tool_args)
                formatted = tool.format_result(result) if hasattr(tool, "format_result") else {"summary": str(result)[:200]}
                _emit("tool_call_result", {"name": tool_name, "result": formatted})

                # ── CB: update explore counters ──
                if phase == "explore":
                    cb = _cb_explore_update(cb, tool_name, result)
                    explore_update = cb.get("explore", {})

                # ── CB: update SQL counters ──
                if tool_name == "submit_sql":
                    cb = _cb_sql_update(cb, result)
                    sql_update = cb.get("sql", {})
                    # Emit STATE_DELTA for frontend
                    if isinstance(result, dict):
                        if result.get("status") == "completed":
                            _emit("state_delta", {"path": "sql", "value": {"sql": result.get("sql", ""), "validation": {"valid": True, "errors": [], "warnings": []}}})
                            _emit("state_delta", {"path": "result", "value": {"columns": result.get("columns", []), "rows": result.get("rows", []), "row_count": result.get("row_count", 0)}})
                        elif result.get("status") == "validation_failed":
                            _emit("state_delta", {"path": "sql", "value": {"sql": result.get("sql", ""), "validation": {"valid": False, "errors": result.get("errors", [])}}})

                # ── CB: global counters ──
                cb = _cb_update(cb, tool_name, tool_args)

                # Build LLM context
                llm_content = formatted.get("summary", str(result))
                detail = formatted.get("detail")
                if detail is not None:
                    try:
                        llm_content = llm_content + "\n\n" + json.dumps(detail, ensure_ascii=False, default=str)
                    except Exception:
                        llm_content = llm_content + "\n\n" + str(detail)
                tool_messages.append(ToolMessage(content=llm_content[:4000], tool_call_id=tc["id"]))
            except Exception as e:
                logger.error("Tool %s failed: %s", tool_name, e)
                _emit("tool_call_result", {"name": tool_name, "error": str(e)})
                tool_messages.append(ToolMessage(content=json.dumps({"error": str(e)}), tool_call_id=tc["id"]))

            _emit("tool_call_end", {"name": tool_name})

        cb["explore"] = explore_update
        cb["sql"] = sql_update
        return {"messages": tool_messages, "cb": cb}

    return node_fn


# ═══════════════════════════════════════════════════════════════════════════════
# Graph builder
# ═══════════════════════════════════════════════════════════════════════════════

def build_graph(db_connection_id: str = "", model: str | None = None) -> StateGraph:
    """Build v3.3 three-phase ReAct graph with circuit breaker.

    START → explore_agent ⇄ explore_tools
               │ (phase advance or CB trigger)
               ▼
            sql_agent ⇄ sql_tools
               │
               ▼
           answer_agent → END
    """
    from app.dependencies import get_llm_client

    builder = StateGraph(AgentState)

    agent_llm = LiteLLMChatAdapter(get_llm_client(model=model, task_type="default"))

    # ── Node factories ──
    def _get_explore_tools():
        return get_explore_tools(db_id=db_connection_id)

    def _get_sql_tools():
        return get_sql_tools(db_id=db_connection_id)

    def _get_answer_tools():
        return get_answer_tools()

    # ── Nodes ──
    builder.add_node("explore_agent", _make_agent_node(agent_llm, _get_explore_tools, lambda: EXPLORE_AGENT_PROMPT, "explore"))
    builder.add_node("explore_tools", _make_tools_node(_get_explore_tools(), "explore"))
    builder.add_node("sql_agent", _make_agent_node(agent_llm, _get_sql_tools, lambda: SQL_AGENT_PROMPT, "sql"))
    builder.add_node("sql_tools", _make_tools_node(_get_sql_tools(), "sql"))
    builder.add_node("answer_agent", _make_agent_node(agent_llm, _get_answer_tools, lambda: ANSWER_AGENT_PROMPT, "answer"))

    # ── Routing ──

    def _extract_tool_calls(state):
        msgs = state.get("messages", [])
        if not msgs:
            return None
        tcs, _ = _parse_tool_calls(msgs[-1])
        return tcs

    def route_explore_agent(state: AgentState) -> str:
        """Explore agent: tools → tools_node, no tools → advance to sql or answer."""
        cb = state.get("cb", {})
        cb_reason = _cb_check(state, "explore")
        if cb_reason:
            cb["cb_reason"] = cb_reason
            # If no tables found at all, skip to answer directly
            explore = cb.get("explore", {})
            if cb_reason in ("search_exhausted",) and not explore.get("tables_found"):
                return "answer_direct"
            return "advance_sql"

        tcs = _extract_tool_calls(state)
        if tcs:
            return "tools"
        # Agent produced no tool calls → ready to advance
        cb["current_phase"] = "sql"
        return "advance_sql"

    def route_explore_tools(state: AgentState) -> str:
        """After explore tools: check CB first, then back to explore agent."""
        cb = state.get("cb", {})
        cb_reason = _cb_check(state, "explore")
        if cb_reason:
            cb["cb_reason"] = cb_reason
            explore = cb.get("explore", {})
            if cb_reason in ("search_exhausted",) and not explore.get("tables_found"):
                return "answer_direct"
            if cb_reason == "explore_max_steps" and explore.get("tables_found"):
                return "advance_sql"
            return "answer_direct"
        return "agent"

    def route_sql_agent(state: AgentState) -> str:
        """SQL agent: tool calls → tools_node, otherwise CB check → answer or loop."""
        cb = state.get("cb", {})
        cb_reason = _cb_check(state, "sql")
        if cb_reason:
            cb["cb_reason"] = cb_reason
            return "answer"

        tcs = _extract_tool_calls(state)
        if tcs:
            return "tools"
        # Agent produced no tool calls → it decided it's done. Advance to answer.
        # Don't auto-advance on sql_status=="completed" — the agent might need
        # more exploration after a successful query.
        cb["current_phase"] = "answer"
        if not cb.get("cb_reason"):
            cb["cb_reason"] = "normal"
        return "answer"

    def route_sql_tools(state: AgentState) -> str:
        """After sql tools: check CB, then back to sql agent."""
        cb = state.get("cb", {})
        cb_reason = _cb_check(state, "sql")
        if cb_reason:
            cb["cb_reason"] = cb_reason
            return "answer"
        return "agent"

    def route_answer_agent(state: AgentState) -> str:
        """Answer agent: final_answer → END, no tools → END (force)."""
        tcs = _extract_tool_calls(state)
        if tcs and any(tc["name"] == "final_answer" for tc in tcs):
            return "end"
        # Force end even without final_answer (safety net)
        return "end"

    # ── Edges ──
    builder.add_edge(START, "explore_agent")

    builder.add_conditional_edges("explore_agent", route_explore_agent, {
        "tools": "explore_tools",
        "advance_sql": "sql_agent",
        "answer_direct": "answer_agent",
    })
    builder.add_conditional_edges("explore_tools", route_explore_tools, {
        "agent": "explore_agent",
        "advance_sql": "sql_agent",
        "answer_direct": "answer_agent",
    })

    builder.add_conditional_edges("sql_agent", route_sql_agent, {
        "tools": "sql_tools",
        "answer": "answer_agent",
    })
    builder.add_conditional_edges("sql_tools", route_sql_tools, {
        "agent": "sql_agent",
        "answer": "answer_agent",
    })

    builder.add_conditional_edges("answer_agent", route_answer_agent, {
        "end": END,
    })

    return builder.compile(checkpointer=MemorySaver())


# ═══════════════════════════════════════════════════════════════════════════════
# Agent Runner
# ═══════════════════════════════════════════════════════════════════════════════

_MONITORING_PATTERNS = [
    "连接状态", "连接数", "多少条", "sql在跑", "运行了多久",
    "数据库状态", "慢查询", "连接信息", "数据库连接",
    "多少连接", "活跃查询", "表概况", "运行时间",
]
_GREETING_PATTERNS = ["你好", "您好", "hi", "hello", "嗨", "在吗", "谢谢", "感谢", "再见", "拜拜"]


async def _greeting_fast_path(conversation_id: str) -> AsyncIterator[str]:
    yield EventEncoder.run_started(conversation_id)
    yield EventEncoder.text_delta("你好！我是 GBase 8a 数据库助手。有什么可以帮你的？")
    yield EventEncoder.run_finished()


async def _monitoring_fast_path(db_connection_id: str | None) -> AsyncIterator[str]:
    if not db_connection_id:
        yield EventEncoder.text_delta("当前未选择数据库连接。请先在左侧设置中添加并选择一个 GBase 8a 数据库连接。")
        yield EventEncoder.run_finished()
        return
    import json as _json
    from app.agents.tools.status_tool import GetDatabaseStatusTool
    tool = GetDatabaseStatusTool(db_connection_id=db_connection_id)
    raw_result = await tool.execute()
    try:
        status_data = raw_result if isinstance(raw_result, dict) else _json.loads(raw_result)
        lines = ["**数据库状态概览**\n"]
        for label, data in status_data.items():
            if isinstance(data, dict) and "error" in data:
                lines.append(f"### {label}\n> 错误: {data['error']}")
            elif isinstance(data, dict) and data.get("rows") and data["rows"]:
                cols = data["columns"]
                line = f"### {label}"
                if len(cols) == 1 and data["row_count"] == 1:
                    line += f"\n{cols[0]}: **{data['rows'][0][0]}**"
                else:
                    line += f"\n| {' | '.join(cols)} |\n|{'|'.join(['---' for _ in cols])}|"
                    for row in data["rows"][:20]:
                        line += f"\n| {' | '.join(str(c) for c in row)} |"
                lines.append(line)
            else:
                lines.append(f"### {label}\n> 无数据")
        formatted = "\n\n".join(lines)
    except (_json.JSONDecodeError, TypeError):
        formatted = f"数据库状态查询结果:\n{raw_result}"
    yield EventEncoder.text_delta(formatted)
    yield EventEncoder.run_finished()


async def run_agent_with_ag_ui(
    user_message: str, conversation_id: str, model: str,
    db_connection_id: str | None = None,
) -> AsyncIterator[str]:
    """运行 v3.3 Circuit Breaker ReAct Agent 并以 AG-UI SSE 流式输出。"""

    if any(user_message.strip().lower().startswith(p) or user_message.strip() == p for p in _GREETING_PATTERNS):
        async for event in _greeting_fast_path(conversation_id):
            yield event
        return

    if any(p in user_message for p in _MONITORING_PATTERNS):
        async for event in _monitoring_fast_path(db_connection_id):
            yield event
        return

    history = []
    if conversation_id:
        try:
            from sqlalchemy import select
            from app.database import async_session_factory
            from app.models.conversation import Conversation
            from app.services.conversation_service import build_context
            async with async_session_factory() as session:
                result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
                conv = result.scalar_one_or_none()
                if conv:
                    ctx = await build_context(session, conv)
                    history = ctx.history or []
        except Exception:
            pass

    graph = build_graph(db_connection_id=db_connection_id or "", model=model)

    initial_state: AgentState = {
        "messages": _build_conversation_messages(history, user_message),
        "db_connection_id": db_connection_id,
        "cb": _cb_init(),
    }

    yield EventEncoder.run_started(conversation_id)
    config = {"configurable": {"thread_id": conversation_id}}
    streamed_text = False

    try:
        async for mode, events in graph.astream(initial_state, config=config, stream_mode=["custom", "updates"]):
            if mode == "custom":
                for ev in events:
                    if isinstance(ev, dict):
                        if "thinking_start" in ev:
                            yield EventEncoder.thinking_start()
                        elif "thinking_delta" in ev:
                            yield EventEncoder.thinking_delta(ev["thinking_delta"])
                        elif "thinking_end" in ev:
                            yield EventEncoder.thinking_end()
                        elif "step_started" in ev:
                            info = ev["step_started"]
                            yield EventEncoder.step_started(info.get("agent_name", "unknown"), info.get("step_index", 0))
                        elif "step_finished" in ev:
                            info = ev["step_finished"]
                            yield EventEncoder.step_finished(info.get("agent_name", "unknown"))
                        elif "tool_call_start" in ev:
                            info = ev["tool_call_start"]
                            yield EventEncoder.tool_call_start(info["name"], info.get("args"), info.get("agent_name", ""))
                        elif "tool_call_result" in ev:
                            info = ev["tool_call_result"]
                            result = info.get("result", {})
                            if "error" in info and "error" not in result:
                                result = {**result, "error": info["error"]} if isinstance(result, dict) else {"error": info["error"]}
                            yield EventEncoder.tool_call_result(info["name"], result)
                        elif "tool_call_end" in ev:
                            info = ev["tool_call_end"]
                            yield EventEncoder.tool_call_end(info.get("name", "unknown"))
                        elif "delta" in ev:
                            yield EventEncoder.text_delta(ev["delta"])
                            streamed_text = True
                        elif "state_delta" in ev:
                            info = ev["state_delta"]
                            yield EventEncoder.state_delta(info["path"], info["value"])

        final_state = await graph.aget_state(config)
        state_values = final_state.values if final_state else {}
        response = state_values.get("final_response", "") if state_values else ""
        if response and not streamed_text:
            yield EventEncoder.text_delta(response)
        yield EventEncoder.run_finished()

    except Exception as e:
        logger.error("Agent run failed: %s", e)
        yield EventEncoder.run_error(str(e))
