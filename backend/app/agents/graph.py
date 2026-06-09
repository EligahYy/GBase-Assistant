"""LangGraph 图构建和运行 — v3.2 Unified ReAct Agent + token 级流式输出。

v3.2 架构: 统一 Agent（全工具集）+ 确定性 SQL Gate + Knowledge Pipeline
- 无独立 Supervisor/router —— Prompt + Tools 本身就是路由机制
- final_answer 工具提供显式终止信号（防无限循环）
- 循环检测 + 三级终止策略（防硬终止丢失进展）
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

from app.agents.agents.knowledge_agent import make_knowledge_node
from app.agents.agents.unified_agent import get_unified_agent_prompt, get_unified_agent_tools
from app.agents.state import AgentState
from app.agents.tools.sql_tools import ExecuteSQLTool
from app.gateway.ag_ui_encoder import EventEncoder
from app.llm.adapter import LiteLLMChatAdapter

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 12  # Reduced from 15 — with final_answer the agent terminates earlier
LOOP_DETECTION_WINDOW = 6  # Look at last N tool calls for loop detection
MILD_WARNING_AT = 8  # Inject mild reminder
URGENT_WARNING_AT = 10  # Inject urgent wrap-up instruction


# ═══════════════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════════════

def _emit(key: str, value: Any) -> None:
    """Emit a custom event through LangGraph's stream writer."""
    try:
        writer = get_stream_writer()
        writer([{key: value}])
    except RuntimeError:
        pass


def _parse_tool_calls(msg) -> tuple[list[dict] | None, str | None]:
    """Extract tool_calls and/or text from a message."""
    tool_calls = None
    text = None

    if hasattr(msg, "tool_calls") and msg.tool_calls:
        tool_calls = []
        for tc in msg.tool_calls:
            tool_calls.append({
                "id": tc.get("id", f"call_{len(tool_calls)}"),
                "name": tc.get("name", ""),
                "args": tc.get("args", {}),
            })

    if hasattr(msg, "content") and msg.content:
        content = msg.content
        if isinstance(content, str) and content.strip():
            text = content.strip()
        elif isinstance(content, list):
            # Some LLMs return content as a list of blocks — join text blocks
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


def _make_ai_message(content: str, tool_calls_data: list[dict] | None = None) -> AIMessage:
    """Build an AIMessage, optionally with tool_calls."""
    if tool_calls_data:
        from langchain_core.messages import ToolCall as LCToolCall
        lc_tool_calls = [
            LCToolCall(name=tc["name"], args=tc.get("args", {}), id=tc.get("id", f"call_{i}"))
            for i, tc in enumerate(tool_calls_data)
        ]
        return AIMessage(content=content, tool_calls=lc_tool_calls)
    return AIMessage(content=content)


async def _call_llm(
    model: Any, messages: list[BaseMessage], tool_schemas: list[dict] | None
) -> AIMessage:
    """Call the LLM and return an AIMessage with tool_calls if present."""
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
        content, _, tool_calls_data = await model.llm_client.complete(
            dict_msgs, tools=tool_schemas if tool_schemas else None
        )
        return _make_ai_message(content or "", tool_calls_data)


def _thinking_summary(agent_name: str, tool_names: list[str]) -> str:
    """Generate a natural-language thinking summary based on agent and tools."""
    TOOL_THINKING: dict[str, str] = {
        "search_schemas": "搜索相关数据库表",
        "get_table_profile": "查看表字段详情",
        "find_join_path": "查找表关联关系",
        "query_glossary": "查询业务术语映射",
        "execute_sql": "执行 SQL 查询",
        "lookup_error": "查询错误码含义",
        "search_knowledge": "检索 GBase 8a 知识库",
        "get_database_status": "获取数据库运行状态",
        "submit_sql": "提交 SQL 验证和执行",
        "final_answer": "整理最终回答",
    }
    actions = [TOOL_THINKING.get(n, n) for n in tool_names]
    if len(actions) == 1:
        return actions[0]
    return "、".join(actions)


def _to_openai_tools(tools: list[Any]) -> list[dict]:
    """Convert tool objects to OpenAI function-calling schema."""
    schemas = []
    for t in tools:
        if hasattr(t, "to_openai_schema"):
            schemas.append(t.to_openai_schema())
    return schemas


def _build_messages(system_prompt: str, state_msgs: list) -> list[BaseMessage]:
    """Build message list: system prompt + existing conversation."""
    return [SystemMessage(content=system_prompt)] + list(state_msgs)


def _build_conversation_messages(history: list[dict], current_message: str) -> list[BaseMessage]:
    """Convert persisted history to LangChain messages and append the current turn once."""
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


# ═══════════════════════════════════════════════════════════════════════════════════
# Loop detection & graceful degradation
# ═══════════════════════════════════════════════════════════════════════════════════

def _detect_loop(state: AgentState) -> bool:
    """Detect if the agent is calling the same tool with similar args repeatedly."""
    msgs = state.get("messages", [])
    recent_calls: list[tuple[str, str]] = []
    for msg in reversed(msgs):
        tcs, _ = _parse_tool_calls(msg)
        if tcs:
            for tc in tcs:
                name = tc.get("name", "")
                # Normalize args for comparison — truncate to catch similar queries
                args_str = json.dumps(tc.get("args", {}), ensure_ascii=False, sort_keys=True)[:80]
                recent_calls.append((name, args_str))
        if len(recent_calls) >= LOOP_DETECTION_WINDOW:
            break

    if len(recent_calls) < 3:
        return False

    # All calls are the same tool → likely loop
    names = {c[0] for c in recent_calls}
    if len(names) == 1:
        return True

    # Same tool + same args pattern (alternating between 2 tools with same args)
    name_counts: dict[str, int] = {}
    for name, args_str in recent_calls:
        name_counts[f"{name}|{args_str}"] = name_counts.get(f"{name}|{args_str}", 0) + 1
    if any(c >= 3 for c in name_counts.values()):
        return True

    return False


def _extract_partial_results(state: AgentState) -> str:
    """Extract partial progress from the state for graceful degradation."""
    parts: list[str] = []
    sql_state = state.get("sql", {})
    if sql_state.get("query_result"):
        parts.append(f"已执行的 SQL 返回了 {sql_state['query_result'].get('row_count', 0)} 行数据。")
    if sql_state.get("generated_sql"):
        parts.append(f"生成的 SQL: `{sql_state['generated_sql'][:200]}`")
    if sql_state.get("grounded_schemas"):
        tables = [getattr(s, "table_name", str(s)) for s in sql_state["grounded_schemas"][:3]]
        parts.append(f"已识别的表: {', '.join(tables)}")

    # Check for knowledge results in messages
    msgs = state.get("messages", [])
    for msg in reversed(msgs):
        if isinstance(msg, ToolMessage) and "search_knowledge" in str(msg.content)[:50]:
            parts.append("已检索知识库但未能充分回答。")
            break

    return "\n".join(parts) if parts else "处理未能完成。"


# ═══════════════════════════════════════════════════════════════════════════════════
# Unified Agent node
# ═══════════════════════════════════════════════════════════════════════════════════

def _make_unified_agent_node(model: Any, get_tools, get_prompt):
    """Create the unified ReAct agent node with final_answer support.

    Key differences from generic _make_agent_node:
    - Detects final_answer tool call → emits answer as delta, signals finish
    - Graduated termination: mild warning → urgent warning → graceful degradation
    - Loop detection: injects wrap-up hint when repeating tools
    """

    async def node_fn(state: AgentState) -> dict:
        tools = get_tools()
        system_prompt = get_prompt()
        step_idx = state.get("agent_step", 0)

        # ── Guard: DB connection required ──
        if step_idx == 0:
            db_id = state.get("db_connection_id")
            if not db_id:
                # No DB connected — still answer, but warn about SQL limitation
                pass  # Let the agent handle it via final_answer

        # ── Level 3: Hard termination with graceful degradation ──
        if step_idx >= MAX_ITERATIONS:
            partial = _extract_partial_results(state)
            msg = (
                f"处理已达最大轮次 ({MAX_ITERATIONS})。以下是基于当前进展的部分结果：\n\n{partial}\n\n"
                "如需更完整的结果，请尝试简化问题或分步提问。"
            )
            _emit("delta", msg)
            _emit("step_finished", {"agent_name": "unified_agent"})
            return {"agent_step": step_idx + 1, "agent_finished": True, "final_response": msg,
                    "messages": [AIMessage(content=msg)]}

        # ── Level 2: Urgent wrap-up warning ──
        if step_idx == URGENT_WARNING_AT:
            urgent_hint = HumanMessage(content=(
                "系统提示：你已执行多轮操作，请立即基于当前已收集的信息调用 final_answer 输出结果。"
                "不要继续探索或调用更多工具。"
            ))
            msgs = list(state.get("messages", [])) + [urgent_hint]
            state = {**state, "messages": msgs}

        # ── Level 1: Mild reminder ──
        elif step_idx == MILD_WARNING_AT:
            mild_hint = HumanMessage(content=(
                "系统提示：已执行多轮操作。如果已有部分结果，可以考虑调用 final_answer 输出，"
                "并说明哪些部分还需要进一步确认。"
            ))
            msgs = list(state.get("messages", [])) + [mild_hint]
            state = {**state, "messages": msgs}

        # ── Loop detection ──
        if step_idx > 2 and _detect_loop(state):
            loop_hint = HumanMessage(content=(
                "系统提示：检测到你多次调用相同工具。请停止重复探索，"
                "基于已有信息调用 final_answer 输出结果。"
            ))
            msgs = list(state.get("messages", [])) + [loop_hint]
            state = {**state, "messages": msgs}

        if step_idx == 0:
            _emit("step_started", {"agent_name": "unified_agent", "step_index": 0})

        msgs = state.get("messages", [])
        messages = _build_messages(system_prompt, msgs)
        tool_schemas = _to_openai_tools(tools)

        try:
            response = await _call_llm(model, messages, tool_schemas if tool_schemas else None)
        except Exception as e:
            logger.error("Unified agent LLM call failed: %s", e)
            _emit("delta", f"\n处理出错: {e}")
            return {"agent_step": step_idx + 1, "agent_finished": True, "messages": [AIMessage(content=f"处理出错: {e}")]}

        tool_calls, text = _parse_tool_calls(response)

        # ── final_answer detected → extract answer, emit as delta, finish ──
        if tool_calls and any(tc["name"] == "final_answer" for tc in tool_calls):
            fa_tc = next(tc for tc in tool_calls if tc["name"] == "final_answer")
            answer = fa_tc.get("args", {}).get("answer", "")
            sources = fa_tc.get("args", {}).get("sources", [])
            if answer:
                _emit("delta", answer)
            if sources:
                _emit("state_delta", {"path": "sources", "value": {"sources": sources}})
            # Emit thinking for any text that preceded final_answer
            if text:
                _emit("thinking_start", {})
                _emit("thinking_delta", text)
                _emit("thinking_end", {})
            _emit("thinking_start", {})
            _emit("thinking_delta", "整理最终回答")
            _emit("thinking_end", {})
            _emit("step_finished", {"agent_name": "unified_agent"})
            return {
                "agent_step": step_idx + 1,
                "agent_finished": True,
                "final_response": answer,
                "messages": [response],
            }

        # ── No tool calls — fallback: treat as final answer if there's text ──
        if not tool_calls:
            if text:
                _emit("delta", text)
                _emit("step_finished", {"agent_name": "unified_agent"})
                return {
                    "agent_step": step_idx + 1,
                    "agent_finished": True,
                    "final_response": text,
                    "messages": [response],
                }
            # Empty response (no tool_calls, no text) — retry LLM call with guidance
            # This prevents silent termination when the LLM returns nothing
            logger.warning("Unified agent returned empty response at step %d — retrying with prompt", step_idx)
            retry_prompt = HumanMessage(content="请调用 final_answer 工具输出你的回答。如果你已经获得了查询结果，请总结结果；如果遇到错误，请说明发生了什么。")
            try:
                retry_messages = messages + [response, retry_prompt]
                response2 = await _call_llm(model, retry_messages, tool_schemas if tool_schemas else None)
                tc2, text2 = _parse_tool_calls(response2)
                if text2:
                    _emit("delta", text2)
                _emit("step_finished", {"agent_name": "unified_agent"})
                return {
                    "agent_step": step_idx + 1,
                    "agent_finished": True,
                    "final_response": text2 or "",
                    "messages": [response, response2],
                }
            except Exception:
                # If retry also fails, terminate gracefully
                fallback = "处理完成。如有其他问题，请继续提问。"
                _emit("delta", fallback)
                _emit("step_finished", {"agent_name": "unified_agent"})
                return {
                    "agent_step": step_idx + 1,
                    "agent_finished": True,
                    "final_response": fallback,
                    "messages": [response],
                }

        # ── Has tool calls (not final_answer) → emit thinking, continue ──
        if text:
            _emit("thinking_start", {})
            _emit("thinking_delta", text)
            _emit("thinking_end", {})

        _emit("thinking_start", {})
        tool_names = [tc["name"] for tc in tool_calls]
        _emit("thinking_delta", _thinking_summary("unified_agent", tool_names))
        _emit("thinking_end", {})
        return {"agent_step": step_idx + 1, "messages": [response]}

    return node_fn


# ═══════════════════════════════════════════════════════════════════════════════════
# Tools node
# ═══════════════════════════════════════════════════════════════════════════════════

def _make_unified_tools_node(tools: list[Any]):
    """Create a tool execution node for the unified agent.

    Reads tool_calls from the last message, executes, emits events.
    Updates sql state for schema/sql tools.
    """

    tool_map = {t.name: t for t in tools if hasattr(t, "name")}

    async def node_fn(state: AgentState) -> dict:
        msgs = state.get("messages", [])
        if not msgs:
            return {"messages": []}

        last_msg = msgs[-1]
        tool_calls, _ = _parse_tool_calls(last_msg)
        if not tool_calls:
            return {"messages": []}

        tool_messages = []
        state_update: dict[str, Any] = {}
        for tc in tool_calls:
            tool_name = tc["name"]
            tool_args = tc.get("args", {})

            _emit("tool_call_start", {"name": tool_name, "args": tool_args, "agent_name": "unified_agent"})

            tool = tool_map.get(tool_name)
            if tool is None:
                _emit("tool_call_result", {"name": tool_name, "error": f"Tool '{tool_name}' not found"})
                _emit("tool_call_end", {"name": tool_name})
                tool_messages.append(ToolMessage(
                    content=json.dumps({"error": f"Tool '{tool_name}' not found"}), tool_call_id=tc["id"]
                ))
                continue

            try:
                result = await tool.execute(**tool_args)
                formatted = tool.format_result(result) if hasattr(tool, "format_result") else {"summary": str(result)[:200]}
                _emit("tool_call_result", {"name": tool_name, "result": formatted})

                # Update SQL state for schema/sql tools
                sql_state = {**state.get("sql", {})}
                if tool_name == "search_schemas":
                    sql_state["grounded_schemas"] = result
                    state_update["sql"] = sql_state
                elif tool_name == "submit_sql":
                    sql_state.update({
                        "generated_sql": result.get("sql", "") if isinstance(result, dict) else "",
                        "phase": "proposed",
                    })
                    state_update["sql"] = sql_state

                # Build LLM context
                llm_content = formatted.get("summary", str(result))
                detail = formatted.get("detail")
                if detail is not None:
                    try:
                        import json as _json
                        llm_content = llm_content + "\n\n" + _json.dumps(detail, ensure_ascii=False, default=str)
                    except Exception:
                        llm_content = llm_content + "\n\n" + str(detail)
                tool_messages.append(ToolMessage(
                    content=llm_content[:4000], tool_call_id=tc["id"]
                ))
            except Exception as e:
                logger.error("Tool %s failed: %s", tool_name, e)
                _emit("tool_call_result", {"name": tool_name, "error": str(e)})
                tool_messages.append(ToolMessage(
                    content=json.dumps({"error": str(e)}), tool_call_id=tc["id"]
                ))

            _emit("tool_call_end", {"name": tool_name})

        return {"messages": tool_messages, **state_update}

    return node_fn


# ═══════════════════════════════════════════════════════════════════════════════════
# SQL validation & execution gates (unchanged from v3.1)
# ═══════════════════════════════════════════════════════════════════════════════════

def _make_sql_validation_node():
    """Create the deterministic SQL validation gate."""

    async def node_fn(state: AgentState) -> dict:
        from app.sql.sandbox import SQLSandbox, SQLSandboxError
        from app.sql.validator import validate_sql

        sql_state = {**state.get("sql", {})}
        sql = str(sql_state.get("generated_sql") or "")
        schemas = sql_state.get("grounded_schemas") or None
        result = validate_sql(sql, schemas=schemas)
        safety_errors: list[str] = []
        try:
            SQLSandbox._validate_first_word(sql)
            SQLSandbox._validate_ast(sql)
            SQLSandbox._validate_single_statement(sql)
        except SQLSandboxError as exc:
            safety_errors.append(str(exc))
        validation = {
            "valid": result.is_valid and not safety_errors,
            "errors": [*safety_errors, *result.errors],
            "warnings": result.warnings,
        }
        sql_state["validation"] = validation
        _emit("state_delta", {"path": "sql", "value": {"sql": sql, "validation": validation}})

        if validation["valid"]:
            sql_state["phase"] = "validated"
            sql_state["execution_error"] = None
            return {"sql": sql_state}

        retry_count = sql_state.get("retry_count", 0) + 1
        sql_state.update({
            "phase": "validation_failed",
            "retry_count": retry_count,
            "execution_error": "；".join(validation["errors"]) or "SQL 验证失败",
        })
        if retry_count >= 3:
            diagnostics = (
                f"SQL 在 3 次尝试后仍未通过验证。\n"
                f"错误：{sql_state['execution_error']}\n"
                f"建议：请检查表名和列名是否正确，或简化查询条件。"
            )
            _emit("delta", diagnostics)
            return {"sql": sql_state, "agent_finished": True, "messages": [AIMessage(content=diagnostics)]}
        feedback = (
            "确定性 SQL 验证失败，请修正后重新调用 submit_sql。"
            f"\n错误：{sql_state['execution_error']}"
        )
        return {"sql": sql_state, "messages": [HumanMessage(content=feedback)]}

    return node_fn


def _make_sql_execution_node(db_connection_id: str):
    """Create the deterministic SQL execution gate.

    On success: returns result to the agent so it can call final_answer.
    On error: returns feedback to the agent so it can fix and retry (up to 3x total).
    Only sets agent_finished when retries are exhausted.
    """

    async def node_fn(state: AgentState) -> dict:
        sql_state = {**state.get("sql", {})}
        sql = str(sql_state.get("generated_sql") or "")
        tool = ExecuteSQLTool(db_connection_id=db_connection_id)
        result = await tool.execute(sql=sql)

        if isinstance(result, dict) and result.get("error"):
            retry_count = sql_state.get("retry_count", 0) + 1
            sql_state.update({
                "phase": "execution_failed",
                "retry_count": retry_count,
                "execution_error": str(result["error"]),
            })
            if retry_count >= 3:
                diagnostics = (
                    f"SQL 执行在 3 次尝试后仍然失败。\n"
                    f"错误：{result['error']}\n"
                    f"生成的 SQL：\n```sql\n{sql}\n```\n"
                    f"建议：请检查数据库连接和表结构是否正确。"
                )
                _emit("delta", diagnostics)
                return {"sql": sql_state, "agent_finished": True, "messages": [AIMessage(content=diagnostics)]}
            feedback = (
                f"SQL 执行失败：{result['error']}\n"
                f"生成的 SQL：\n```sql\n{sql}\n```\n"
                f"请修正后重新调用 submit_sql。已尝试 {retry_count}/3 次。"
            )
            return {"sql": sql_state, "messages": [HumanMessage(content=feedback)]}

        # Success — return result to agent for final_answer, DON'T terminate
        sql_state.update({
            "phase": "completed",
            "query_result": result,
            "execution_error": None,
        })
        _emit("state_delta", {"path": "result", "value": result})
        result_msg = (
            f"```sql\n{sql}\n```\n\n"
            f"查询完成：共 {result.get('row_count', 0)} 行，耗时 {result.get('execution_time_ms', 0)}ms。\n\n"
            f"请调用 final_answer 向用户展示和分析查询结果。"
        )
        _emit("delta", result_msg)
        return {"sql": sql_state, "messages": [AIMessage(content=result_msg)]}

    return node_fn


# ═══════════════════════════════════════════════════════════════════════════════════
# Graph builder — v3.2 Unified Agent
# ═══════════════════════════════════════════════════════════════════════════════════

def build_graph(db_connection_id: str = "", model: str | None = None) -> StateGraph:
    """Build the v3.2 Unified ReAct Agent graph.

    Graph structure (5 nodes):
        START → unified_agent ⇄ unified_tools
                   │                │
                   │           submit_sql → sql_validate → sql_execute → unified_agent
                   │
                   └── final_answer / agent_finished → END
    """
    from app.dependencies import get_llm_client

    builder = StateGraph(AgentState)

    agent_llm = LiteLLMChatAdapter(get_llm_client(model=model, task_type="default"))

    def _get_tools():
        return get_unified_agent_tools(db_id=db_connection_id)

    # ── Nodes ──
    builder.add_node("unified_agent", _make_unified_agent_node(
        agent_llm, _get_tools, get_unified_agent_prompt,
    ))
    builder.add_node("unified_tools", _make_unified_tools_node(_get_tools()))
    builder.add_node("sql_validate", _make_sql_validation_node())
    builder.add_node("sql_execute", _make_sql_execution_node(db_connection_id))

    # ── Routing ──

    def route_unified_agent(state: AgentState) -> str:
        """Route from unified_agent: final_answer/finished → END, any tool calls → tools_node."""
        if state.get("agent_finished"):
            return "end"

        msgs = state.get("messages", [])
        if not msgs:
            return "end"

        last = msgs[-1]
        tcs, _ = _parse_tool_calls(last)

        if not tcs:
            return "end"

        tc_names = [tc["name"] for tc in tcs]

        if "final_answer" in tc_names:
            return "end"

        # All other tool calls (including submit_sql) go through tools_node
        # so the sql state gets populated before validation
        return "tools"

    def route_after_tools(state: AgentState) -> str:
        """After tools: submit_sql → validate, else back to agent."""
        sql_state = state.get("sql", {})
        if sql_state.get("phase") == "proposed":
            return "validate"
        return "agent"

    def route_after_validate(state: AgentState) -> str:
        """After SQL validation: valid → execute, max retries → agent (final_answer), else → agent (retry)."""
        sql_state = state.get("sql", {})
        if sql_state.get("validation", {}).get("valid"):
            return "execute"
        return "agent"  # Agent receives error feedback and can retry or final_answer

    def route_after_execute(state: AgentState) -> str:
        """After SQL execution: always back to agent (for final_answer)."""
        return "agent"

    # ── Edges ──
    builder.add_edge(START, "unified_agent")

    builder.add_conditional_edges("unified_agent", route_unified_agent, {
        "tools": "unified_tools",
        "end": END,
    })

    builder.add_conditional_edges("unified_tools", route_after_tools, {
        "validate": "sql_validate",
        "agent": "unified_agent",
    })

    builder.add_conditional_edges("sql_validate", route_after_validate, {
        "execute": "sql_execute",
        "agent": "unified_agent",
    })

    builder.add_conditional_edges("sql_execute", route_after_execute, {
        "agent": "unified_agent",
    })

    return builder.compile(checkpointer=MemorySaver())


# ═══════════════════════════════════════════════════════════════════════════════════
# Agent Runner
# ═══════════════════════════════════════════════════════════════════════════════════

_MONITORING_PATTERNS = [
    "连接状态", "连接数", "多少条", "sql在跑", "运行了多久",
    "数据库状态", "慢查询", "连接信息", "数据库连接",
    "多少连接", "活跃查询", "表概况", "运行时间",
]

_GREETING_PATTERNS = ["你好", "您好", "hi", "hello", "嗨", "在吗", "谢谢", "感谢", "再见", "拜拜"]


async def _greeting_fast_path(conversation_id: str) -> AsyncIterator[str]:
    """Respond to simple greetings directly without invoking any agent."""
    yield EventEncoder.run_started(conversation_id)
    yield EventEncoder.text_delta("你好！我是 GBase 8a 数据库助手。有什么可以帮你的？")
    yield EventEncoder.run_finished()


async def _monitoring_fast_path(db_connection_id: str | None) -> AsyncIterator[str]:
    """Execute database status query directly, bypassing the Agent graph."""
    if not db_connection_id:
        yield EventEncoder.text_delta("当前未选择数据库连接。请先在左侧设置中添加并选择一个 GBase 8a 数据库连接。")
        yield EventEncoder.run_finished()
        return

    import json

    from app.agents.tools.status_tool import GetDatabaseStatusTool

    tool = GetDatabaseStatusTool(db_connection_id=db_connection_id)
    raw_result = await tool.execute()

    try:
        status_data = raw_result if isinstance(raw_result, dict) else json.loads(raw_result)
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
                    line += f"\n| {' | '.join(cols)} |"
                    line += f"\n|{'|'.join(['---' for _ in cols])}|"
                    for row in data["rows"][:20]:
                        line += f"\n| {' | '.join(str(c) for c in row)} |"
                lines.append(line)
            else:
                lines.append(f"### {label}\n> 无数据")
        formatted = "\n\n".join(lines)
    except (json.JSONDecodeError, TypeError):
        formatted = f"数据库状态查询结果:\n{raw_result}"

    yield EventEncoder.text_delta(formatted)
    yield EventEncoder.run_finished()


async def run_agent_with_ag_ui(
    user_message: str,
    conversation_id: str,
    model: str,
    db_connection_id: str | None = None,
) -> AsyncIterator[str]:
    """运行 v3.2 Unified ReAct Agent 并以 AG-UI SSE 流式输出。"""

    # ── 问候快速路径 ──
    if any(user_message.strip().lower().startswith(p) or user_message.strip() == p for p in _GREETING_PATTERNS):
        async for event in _greeting_fast_path(conversation_id):
            yield event
        return

    # ── 监控快速路径 ──
    if any(p in user_message for p in _MONITORING_PATTERNS):
        async for event in _monitoring_fast_path(db_connection_id):
            yield event
        return

    # Load conversation history
    history = []
    if conversation_id:
        try:
            from sqlalchemy import select

            from app.database import async_session_factory
            from app.models.conversation import Conversation
            from app.services.conversation_service import build_context

            async with async_session_factory() as session:
                result = await session.execute(
                    select(Conversation).where(Conversation.id == conversation_id)
                )
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
        "agent_step": 0,
        "agent_finished": False,
        "sql": {"retry_count": 0, "phase": "idle"},
    }

    yield EventEncoder.run_started(conversation_id)

    config = {"configurable": {"thread_id": conversation_id}}
    streamed_text = False

    try:
        async for mode, events in graph.astream(
            initial_state, config=config, stream_mode=["custom", "updates"]
        ):
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
                            yield EventEncoder.tool_call_start(
                                info["name"], info.get("args"), info.get("agent_name", "")
                            )
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
