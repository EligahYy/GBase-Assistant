"""Custom ReAct Agent factory with streaming THINKING + TOOL_CALL events.

Replaces langgraph.prebuilt.create_react_agent to gain control over:
- Thinking content streaming (THINKING_START/CONTENT/END)
- Tool call lifecycle events (TOOL_CALL_START/RESULT/END)
- Step lifecycle (STEP_STARTED/FINISHED)
- Iteration limits with graceful termination
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langgraph.graph import StateGraph, START, END
from langgraph.config import get_stream_writer
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.language_models import BaseChatModel

from app.agents.state import ReActState

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 15


def _emit_custom(key: str, value: Any) -> None:
    """Emit a custom event through LangGraph's stream writer."""
    try:
        writer = get_stream_writer()
        writer([{key: value}])
    except RuntimeError:
        pass  # Not in a streaming context (e.g., tests)


def _parse_tool_calls(response: AIMessage) -> tuple[list[dict] | None, str | None]:
    """Extract tool calls and/or text content from an AI message.

    Returns (tool_calls_list, text_content). One or both may be None.
    """
    tool_calls = None
    text = None

    # Check for native tool_calls (when model natively supports function calling)
    if hasattr(response, "tool_calls") and response.tool_calls:
        tool_calls = []
        for tc in response.tool_calls:
            tool_calls.append({
                "id": tc.get("id", f"call_{len(tool_calls)}"),
                "name": tc["name"],
                "args": tc.get("args", {}),
            })

    # Check for text content
    if hasattr(response, "content") and response.content:
        content = response.content
        if isinstance(content, str):
            text = content.strip()

    return tool_calls, text


def _build_react_agent_node(
    model: BaseChatModel,
    tools: list[Any],
    system_prompt: str,
    agent_name: str,
):
    """Create the agent reasoning node — streams THINKING events, returns tool_calls or text."""

    async def node_fn(state: ReActState) -> dict:
        step_index = state.get("step_index", 0)

        # Emit STEP_STARTED on first iteration
        if step_index == 0:
            _emit_custom("step_started", {"agent_name": agent_name, "step_index": 0})

        # Build messages: system prompt + conversation history
        messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
        existing = state.get("messages", [])
        messages.extend(existing)

        # Build tool schemas for the LLM
        tool_schemas = []
        for t in tools:
            if hasattr(t, "to_openai_schema"):
                tool_schemas.append(t.to_openai_schema())

        # ── Call LLM ──
        full_response: AIMessage | None = None

        try:
            if hasattr(model, "_agenerate"):
                result = await model._agenerate(messages, tools=tool_schemas if tool_schemas else None)
                if result.generations and result.generations[0]:
                    full_response = result.generations[0].message
            elif hasattr(model, "ainvoke"):
                kwargs = {}
                if tool_schemas:
                    kwargs["tools"] = tool_schemas
                full_response = await model.ainvoke(messages, **kwargs)
            else:
                # Fallback: use LiteLLM adapter's complete method
                dict_msgs = []
                for m in messages:
                    role = "system" if isinstance(m, SystemMessage) else "user"
                    if hasattr(m, "type"):
                        role = "assistant" if m.type == "ai" else ("system" if m.type == "system" else "user")
                    dict_msgs.append({"role": role, "content": str(m.content)})
                content, _ = await model.llm_client.complete(dict_msgs, tools=tool_schemas if tool_schemas else None)
                full_response = AIMessage(content=content)
        except Exception as e:
            logger.error("ReAct agent %s LLM call failed: %s", agent_name, e)
            error_msg = AIMessage(content=f"处理出错: {e}")
            _emit_custom("delta", f"\n处理出错: {e}")
            return {"messages": [error_msg], "finished": True, "step_index": step_index + 1}

        # Parse response
        tool_calls, text = _parse_tool_calls(full_response)

        if text and not tool_calls:
            # Final text answer — emit as regular text
            _emit_custom("delta", text)
            return {
                "messages": [full_response],
                "finished": True,
                "step_index": step_index + 1,
            }

        if tool_calls:
            # Emit a brief thinking summary about the tool choice
            thinking_summary = f"调用 {len(tool_calls)} 个工具: {', '.join(tc['name'] for tc in tool_calls)}"
            _emit_custom("thinking_start", {})
            _emit_custom("thinking_delta", thinking_summary)
            _emit_custom("thinking_end", {})

            return {
                "messages": [full_response],
                "step_index": step_index + 1,
            }

        # No tool calls and no text — force end
        fallback = AIMessage(content="处理完成。")
        _emit_custom("delta", "处理完成。")
        return {"messages": [fallback], "finished": True, "step_index": step_index + 1}

    return node_fn


def _build_tool_execution_node(tools: list[Any], agent_name: str):
    """Create the tool execution node — emits TOOL_CALL_START/RESULT/END events."""

    async def node_fn(state: ReActState) -> dict:
        messages = state.get("messages", [])
        if not messages:
            return {"messages": []}

        last_msg = messages[-1]
        tool_calls, _ = _parse_tool_calls(last_msg)

        if not tool_calls:
            return {"messages": []}

        # Build name → tool mapping
        tool_map = {t.name: t for t in tools if hasattr(t, "name")}

        tool_messages = []
        for tc in tool_calls:
            tool_name = tc["name"]
            tool_args = tc.get("args", {})

            # Emit TOOL_CALL_START
            _emit_custom("tool_call_start", {
                "name": tool_name,
                "args": tool_args,
                "agent_name": agent_name,
            })

            tool = tool_map.get(tool_name)
            if tool is None:
                error_msg = f"Tool '{tool_name}' not found"
                _emit_custom("tool_call_result", {"name": tool_name, "error": error_msg})
                _emit_custom("tool_call_end", {"name": tool_name})
                tool_messages.append(ToolMessage(content=json.dumps({"error": error_msg}), tool_call_id=tc["id"]))
                continue

            try:
                result = await tool.execute(**tool_args)

                if hasattr(tool, "format_result"):
                    formatted = tool.format_result(result)
                else:
                    formatted = {"summary": str(result)[:200], "detail": None, "truncated": False}

                _emit_custom("tool_call_result", {
                    "name": tool_name,
                    "result": formatted,
                })

                tool_messages.append(ToolMessage(
                    content=formatted.get("summary", str(result)),
                    tool_call_id=tc["id"],
                ))

            except Exception as e:
                logger.error("Tool %s execution failed: %s", tool_name, e)
                _emit_custom("tool_call_result", {"name": tool_name, "error": str(e)})
                tool_messages.append(ToolMessage(
                    content=json.dumps({"error": str(e)}),
                    tool_call_id=tc["id"],
                ))

            _emit_custom("tool_call_end", {"name": tool_name})

        return {"messages": tool_messages}

    return node_fn


def _make_router(agent_name: str):
    """Create a route_after_agent function with agent_name captured in closure."""

    def _route_after_agent(state: ReActState) -> str:
        """Route: if agent has tool calls → tools node, else → END."""
        step_index = state.get("step_index", 0)
        max_iter = state.get("max_iterations", MAX_ITERATIONS)

        if state.get("finished"):
            _emit_custom("step_finished", {"agent_name": agent_name})
            return "end"

        if step_index >= max_iter:
            logger.warning("ReAct agent reached max iterations (%d), forcing end", max_iter)
            _emit_custom("step_finished", {"agent_name": agent_name})
            return "end"

        messages = state.get("messages", [])
        if not messages:
            _emit_custom("step_finished", {"agent_name": agent_name})
            return "end"

        last_msg = messages[-1]
        tool_calls, _ = _parse_tool_calls(last_msg)

        if tool_calls:
            return "tools"

        _emit_custom("step_finished", {"agent_name": agent_name})
        return "end"

    return _route_after_agent


def build_react_agent(
    model: BaseChatModel,
    tools: list[Any],
    system_prompt: str,
    agent_name: str,
    max_iterations: int = MAX_ITERATIONS,
) -> StateGraph:
    """Build a custom ReAct Agent subgraph with streaming observability.

    Args:
        model: LangChain-compatible chat model
        tools: List of AgentTool instances
        system_prompt: System prompt for the agent
        agent_name: Name for event emission (e.g. "sql_agent", "supervisor")
        max_iterations: Hard limit on tool-calling iterations (default 15)

    Returns:
        Compiled LangGraph StateGraph ready to use as a subgraph node
    """
    builder = StateGraph(ReActState)

    agent_node = _build_react_agent_node(model, tools, system_prompt, agent_name)
    tools_node = _build_tool_execution_node(tools, agent_name)

    builder.add_node("agent", agent_node)
    builder.add_node("tools", tools_node)

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", _make_router(agent_name), {
        "tools": "tools",
        "end": END,
    })
    builder.add_edge("tools", "agent")

    return builder.compile()
