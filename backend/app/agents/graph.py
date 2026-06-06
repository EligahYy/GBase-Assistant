"""LangGraph 图构建和运行 — v3 ReAct Multi-Agent + token 级流式输出。

Supervisor Agent (ReAct + 5 tools) 动态委托给 SQL / Knowledge SubGraph。
每个 SubGraph 是独立的 ReAct 循环，工具调用全过程流式可见。
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langchain_core.messages import AIMessage, HumanMessage

from app.agents.state import V3AgentState
from app.agents.agents.react_agent import build_react_agent
from app.agents.agents.supervisor import get_supervisor_tools, get_supervisor_prompt
from app.agents.agents.sql_agent import get_sql_agent_tools, get_sql_agent_prompt
from app.agents.agents.knowledge_agent import get_knowledge_agent_tools, get_knowledge_agent_prompt
from app.llm.adapter import LiteLLMChatAdapter
from app.gateway.ag_ui_encoder import EventEncoder

logger = logging.getLogger(__name__)


# ── 图构建 ──

def build_graph(db_connection_id: str = "") -> StateGraph:
    """Build v3 ReAct Agent graph: Supervisor → (SQL | Knowledge) SubGraphs.

    Supervisor is a ReAct agent that dynamically delegates to specialist sub-agents.
    Each specialist is itself a ReAct agent with its own tool set.
    """
    from app.dependencies import get_llm_client

    builder = StateGraph(V3AgentState)

    supervisor_llm = get_llm_client(task_type="general")
    specialist_llm = get_llm_client(task_type="sql")

    # Build sub-agents
    supervisor_subgraph = build_react_agent(
        model=LiteLLMChatAdapter(supervisor_llm),
        tools=get_supervisor_tools(db_connection_id),
        system_prompt=get_supervisor_prompt(),
        agent_name="supervisor",
    )

    sql_subgraph = build_react_agent(
        model=LiteLLMChatAdapter(specialist_llm),
        tools=get_sql_agent_tools(db_id=db_connection_id, db_connection_id=db_connection_id),
        system_prompt=get_sql_agent_prompt(),
        agent_name="sql_agent",
    )

    knowledge_subgraph = build_react_agent(
        model=LiteLLMChatAdapter(specialist_llm),
        tools=get_knowledge_agent_tools(),
        system_prompt=get_knowledge_agent_prompt(),
        agent_name="knowledge_agent",
    )

    builder.add_node("supervisor", supervisor_subgraph)
    builder.add_node("sql_agent", sql_subgraph)
    builder.add_node("knowledge_agent", knowledge_subgraph)
    builder.add_node("response_formatter", _response_formatter_node)

    builder.add_edge(START, "supervisor")

    def route_supervisor(state):
        msgs = state.get("messages", [])
        if not msgs:
            return "response_formatter"
        # Search all messages in reverse for the most recent tool call
        for msg in reversed(msgs):
            if hasattr(msg, "tool_calls") and msg.tool_calls:
                for tc in msg.tool_calls:
                    name = tc.get("name", "")
                    if name == "delegate_to_sql_specialist":
                        return "sql_agent"
                    if name == "delegate_to_knowledge_specialist":
                        return "knowledge_agent"
                    if name in ("respond_general", "ask_user_clarification", "get_database_status"):
                        return "response_formatter"
                break
        return "response_formatter"

    builder.add_conditional_edges("supervisor", route_supervisor, {
        "sql_agent": "sql_agent",
        "knowledge_agent": "knowledge_agent",
        "response_formatter": "response_formatter",
    })

    # Sub-agents return to supervisor for possible re-delegation
    builder.add_edge("sql_agent", "supervisor")
    builder.add_edge("knowledge_agent", "supervisor")
    builder.add_edge("response_formatter", END)

    return builder.compile(checkpointer=MemorySaver())


async def _response_formatter_node(state: V3AgentState) -> dict:
    """Format the final response — extract last AIMessage text content."""
    msgs = state.get("messages", [])
    final_text = ""

    for msg in reversed(msgs):
        if isinstance(msg, AIMessage) and msg.content:
            content = msg.content
            if isinstance(content, str) and content.strip():
                # Skip delegate tool call response payloads
                if content.strip().startswith('{"status":'):
                    continue
                final_text = content
                break

    if not final_text:
        final_text = "处理完成。如有其他问题，请继续提问。"

    return {"final_response": final_text}


# ── Agent Runner（AG-UI 流式输出） ──

async def _run_agent(
    user_message: str,
    conversation_id: str,
    model: str,
    db_connection_id: str | None = None,
) -> AsyncIterator[str]:
    """Run ReAct Agent graph with full streaming observability."""
    graph = build_graph(db_connection_id=db_connection_id or "")

    history = []
    if conversation_id:
        try:
            from app.database import async_session_factory
            from app.models.conversation import Conversation
            from app.services.conversation_service import build_context
            from sqlalchemy import select

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

    initial_state: V3AgentState = {
        "messages": [HumanMessage(content=user_message)],
        "conversation_id": conversation_id,
        "model": model,
        "db_connection_id": db_connection_id,
        "history": history,
        "supervisor": {},
        "sql": {},
        "knowledge": {},
    }

    yield EventEncoder.run_started(conversation_id)

    config = {"configurable": {"thread_id": f"v3_{conversation_id}"}}
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
                            yield EventEncoder.step_started(
                                info.get("agent_name", "unknown"),
                                info.get("step_index", 0),
                            )
                        elif "step_finished" in ev:
                            info = ev["step_finished"]
                            yield EventEncoder.step_finished(
                                info.get("agent_name", "unknown")
                            )
                        elif "tool_call_start" in ev:
                            info = ev["tool_call_start"]
                            yield EventEncoder.tool_call_start(
                                info["name"], info.get("args")
                            )
                        elif "tool_call_result" in ev:
                            info = ev["tool_call_result"]
                            yield EventEncoder.tool_call_result(
                                info["name"], info.get("result", {})
                            )
                        elif "tool_call_end" in ev:
                            info = ev["tool_call_end"]
                            yield EventEncoder.tool_call_end(
                                info.get("name", "unknown")
                            )
                        elif "delta" in ev:
                            yield EventEncoder.text_delta(ev["delta"])
                            streamed_text = True

        final_state = await graph.aget_state(config)
        state_values = final_state.values if final_state else {}
        response = state_values.get("final_response", "") if state_values else ""

        if response and not streamed_text:
            yield EventEncoder.text_delta(response)

        yield EventEncoder.run_finished()

    except Exception as e:
        logger.error("Agent run failed: %s", e)
        yield EventEncoder.run_error(str(e))


async def run_agent_with_ag_ui(
    user_message: str,
    conversation_id: str,
    model: str,
    db_connection_id: str | None = None,
) -> AsyncIterator[str]:
    """运行 v3 ReAct Agent 并以 AG-UI token 级流式 SSE 输出。"""
    async for event in _run_agent(user_message, conversation_id, model, db_connection_id):
        yield event
