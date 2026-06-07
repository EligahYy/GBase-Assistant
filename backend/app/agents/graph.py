"""LangGraph 图构建和运行 — v3 ReAct Multi-Agent + token 级流式输出。

所有 Agent 节点内联到主图中（非编译子图），确保 get_stream_writer()
的 custom events 正确传播到 AG-UI SSE 流。
"""

from __future__ import annotations

import json
import logging
from collections.abc import AsyncIterator
from typing import Any

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage

from app.agents.state import AgentState
from app.agents.agents.supervisor import get_supervisor_tools, get_supervisor_prompt
from app.agents.agents.sql_agent import get_sql_agent_tools, get_sql_agent_prompt
from app.agents.agents.knowledge_agent import get_knowledge_agent_tools, get_knowledge_agent_prompt
from app.agents.agents.general_agent import get_general_agent_prompt
from app.llm.adapter import LiteLLMChatAdapter
from app.gateway.ag_ui_encoder import EventEncoder

logger = logging.getLogger(__name__)

MAX_DELEGATIONS = 3
MAX_ITERATIONS = 15


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
    # Map tool names to human-readable actions for thinking display
    TOOL_THINKING: dict[str, str] = {
        "search_schemas": "搜索相关数据库表",
        "get_table_profile": "查看表字段详情",
        "find_join_path": "查找表关联关系",
        "query_glossary": "查询业务术语映射",
        "validate_sql": "验证 SQL 语法",
        "execute_sql": "执行 SQL 查询",
        "lookup_error": "查询错误码含义",
        "search_knowledge": "检索 GBase 8a 知识库",
        "get_database_status": "获取数据库运行状态",
        "delegate_to_sql_specialist": "委托 SQL 专家处理查询",
        "delegate_to_knowledge_specialist": "委托知识专家检索文档",
        "delegate_to_general": "处理对话",
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


# ═══════════════════════════════════════════════════════════════════════════════════
# Agent nodes (inlined — NOT compiled subgraphs)
# ═══════════════════════════════════════════════════════════════════════════════════

def _make_agent_node(model: Any, get_tools, get_prompt, agent_name: str, step_key: str, finished_key: str, isolate_context: bool = False):
    """Create a ReAct agent reasoning node with per-agent iteration + finish tracking.

    Args:
        isolate_context: If True, only show the user's original question + this agent's
            own messages. Supervisor delegation chatter is excluded. Use for specialists.
    """

    async def node_fn(state: AgentState) -> dict:
        tools = get_tools()
        system_prompt = get_prompt()
        step_idx = state.get(step_key, 0)

        # ── Guard: SQL Agent requires a database connection ──
        if agent_name == "sql_agent" and step_idx == 0:
            db_id = state.get("db_connection_id")
            if not db_id:
                msg = "当前未选择数据库连接。请先在左侧设置中添加并选择一个 GBase 8a 数据库连接，然后再进行数据查询。"
                _emit("delta", msg)
                _emit("step_finished", {"agent_name": agent_name})
                return {step_key: 1, finished_key: True, "messages": [AIMessage(content=msg)]}

        # ── Guard: iteration limit reached ──
        if step_idx >= MAX_ITERATIONS:
            msg = "处理超时：当前任务超过了最大处理次数，请尝试简化您的问题或换个方式描述。"
            _emit("delta", msg)
            _emit("step_finished", {"agent_name": agent_name})
            return {step_key: step_idx + 1, finished_key: True, "messages": [AIMessage(content=msg)]}

        if step_idx == 0:
            _emit("step_started", {"agent_name": agent_name, "step_index": 0})

        msgs = state.get("messages", [])
        if isolate_context and step_idx == 0:
            # Specialist agent: only include the original user question (first HumanMessage)
            # + this agent's own messages. Supervisor delegation chatter is excluded.
            user_msg = None
            for m in msgs:
                if isinstance(m, HumanMessage):
                    user_msg = m
                    break
            msgs = [user_msg] if user_msg else msgs

        messages = _build_messages(system_prompt, msgs)
        tool_schemas = _to_openai_tools(tools)

        try:
            response = await _call_llm(model, messages, tool_schemas if tool_schemas else None)
        except Exception as e:
            logger.error("Agent %s LLM call failed: %s", agent_name, e)
            _emit("delta", f"\n处理出错: {e}")
            return {step_key: step_idx + 1, finished_key: True, "messages": [AIMessage(content=f"处理出错: {e}")]}

        tool_calls, text = _parse_tool_calls(response)

        if not tool_calls:
            # Pure text response — agent is done
            if text:
                _emit("delta", text)
            _emit("step_finished", {"agent_name": agent_name})
            return {step_key: step_idx + 1, finished_key: True, "messages": [response]}

        # Has tool calls — emit text (if any) as THINKING, not as visible content
        # This prevents internal reasoning like "我来帮您查询..." from appearing in the response
        if text:
            _emit("thinking_start", {})
            _emit("thinking_delta", text)
            _emit("thinking_end", {})

        _emit("thinking_start", {})
        # Natural-language thinking summary
        tool_names = [tc['name'] for tc in tool_calls]
        _emit("thinking_delta", _thinking_summary(agent_name, tool_names))
        _emit("thinking_end", {})
        return {step_key: step_idx + 1, "messages": [response]}

    return node_fn


def _make_tools_node(tools: list[Any], agent_name: str):
    """Create a tool execution node. Reads tool_calls from the last message, executes, emits events."""

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
        for tc in tool_calls:
            tool_name = tc["name"]
            tool_args = tc.get("args", {})

            _emit("tool_call_start", {"name": tool_name, "args": tool_args, "agent_name": agent_name})

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
                # Build LLM context: always include full detail so the LLM can reason.
                # Frontend gets summary; LLM gets summary + detail for grounding.
                llm_content = formatted.get("summary", str(result))
                detail = formatted.get("detail")
                if detail is not None:
                    try:
                        import json as _json
                        llm_content = llm_content + "\n\n" + _json.dumps(detail, ensure_ascii=False, default=str)
                    except Exception:
                        llm_content = llm_content + "\n\n" + str(detail)
                tool_messages.append(ToolMessage(
                    content=llm_content[:4000], tool_call_id=tc["id"]  # Cap at 4000 chars
                ))
            except Exception as e:
                logger.error("Tool %s failed: %s", tool_name, e)
                _emit("tool_call_result", {"name": tool_name, "error": str(e)})
                tool_messages.append(ToolMessage(
                    content=json.dumps({"error": str(e)}), tool_call_id=tc["id"]
                ))

            _emit("tool_call_end", {"name": tool_name})

        return {"messages": tool_messages}

    return node_fn


# ═══════════════════════════════════════════════════════════════════════════════════
# Knowledge Agent — search→answer pipeline (NOT ReAct, no tools for LLM)
# ═══════════════════════════════════════════════════════════════════════════════════

def _make_knowledge_node(model: Any):
    """Knowledge agent: auto-search → LLM formats answer (no ReAct, no tools for LLM).

    Uses the same retrieval + prompt pattern as v2's proven knowledge_specialist_node.
    """

    async def node_fn(state: AgentState) -> dict:
        _emit("step_started", {"agent_name": "knowledge_agent", "step_index": 0})

        msgs = state.get("messages", [])
        user_msg = None
        for m in msgs:
            if isinstance(m, HumanMessage):
                user_msg = m.content if hasattr(m, "content") else str(m)
                break
        if not user_msg:
            user_msg = str(msgs[-1].content) if msgs else ""

        # ── Phase 1: Search knowledge base (same retriever as v2) ──
        _emit("thinking_start", {})
        _emit("thinking_delta", "检索 GBase 8a 知识库")
        _emit("thinking_end", {})

        from app.dependencies import get_knowledge_retriever
        retriever = get_knowledge_retriever()
        chunks = await retriever.retrieve(user_msg)

        _emit("tool_call_start", {"name": "search_knowledge", "args": {"query": str(user_msg)[:100]}, "agent_name": "knowledge_agent"})
        _emit("tool_call_result", {"name": "search_knowledge", "result": {"summary": f"检索到 {len(chunks)} 条相关文档"}})
        _emit("tool_call_end", {"name": "search_knowledge"})

        # ── Phase 2: Use v2's proven QA prompt pattern ──
        from app.llm.prompts import build_qa_prompt
        messages = build_qa_prompt(message=user_msg, knowledge_chunks=chunks, history=state.get("history", []))

        try:
            response = await _call_llm(model, messages, None)
            _, text = _parse_tool_calls(response)
            answer = text or "知识库中未找到相关信息，建议查阅 GBase 8a 官方手册。"
        except Exception as e:
            logger.error("Knowledge agent LLM call failed: %s", e)
            answer = f"知识检索处理出错: {e}"

        _emit("delta", answer)
        _emit("step_finished", {"agent_name": "knowledge_agent"})
        return {"knowledge_finished": True, "messages": [AIMessage(content=answer)]}

    return node_fn


# ═══════════════════════════════════════════════════════════════════════════════════
# Graph builder
# ═══════════════════════════════════════════════════════════════════════════════════

def build_graph(db_connection_id: str = "") -> StateGraph:
    """Build v3 ReAct Agent graph with inlined agent+tools nodes.

    Graph structure:
        START → supervisor_agent ⇄ supervisor_tools
                    │ (delegate_to_sql)
                    ├──→ sql_agent ⇄ sql_tools ──→ supervisor_agent
                    │ (delegate_to_knowledge)
                    ├──→ knowledge_agent ⇄ knowledge_tools ──→ supervisor_agent
                    │ (respond_general / ask_clarify / get_status)
                    └──→ response_formatter → END
    """
    from app.dependencies import get_llm_client

    builder = StateGraph(AgentState)

    supervisor_llm = LiteLLMChatAdapter(get_llm_client(task_type="general"))
    specialist_llm = LiteLLMChatAdapter(get_llm_client(task_type="sql"))

    # ── Node factories (capture db_connection_id in closure) ──

    def _get_supervisor_tools():
        return get_supervisor_tools(db_connection_id)

    def _get_sql_tools():
        return get_sql_agent_tools(db_id=db_connection_id, db_connection_id=db_connection_id)

    def _get_knowledge_tools():
        return get_knowledge_agent_tools()

    def _get_no_tools():
        return []  # General agent has no tools

    # ── Add nodes ──

    builder.add_node("supervisor_agent", _make_agent_node(
        supervisor_llm, _get_supervisor_tools, get_supervisor_prompt, "supervisor", "supervisor_step", "supervisor_finished"
    ))
    builder.add_node("supervisor_tools", _make_tools_node(_get_supervisor_tools(), "supervisor"))

    builder.add_node("sql_agent", _make_agent_node(
        specialist_llm, _get_sql_tools, get_sql_agent_prompt, "sql_agent", "sql_step", "sql_finished",
        isolate_context=True,
    ))
    builder.add_node("sql_tools", _make_tools_node(_get_sql_tools(), "sql_agent"))

    # Knowledge Agent: auto-search → LLM formats answer (NOT ReAct — no tools, no loop)
    builder.add_node("knowledge_agent", _make_knowledge_node(specialist_llm))

    builder.add_node("general_agent", _make_agent_node(
        supervisor_llm, _get_no_tools, get_general_agent_prompt, "general_agent", "general_step", "general_finished",
        isolate_context=True,
    ))

    builder.add_node("response_formatter", _response_formatter_node)

    # ── Routing ──

    def _route_agent(state: AgentState, step_key: str, finished_key: str) -> str:
        if state.get(finished_key):
            return "end"
        step = state.get(step_key, 0)
        if step >= MAX_ITERATIONS:
            return "end"
        msgs = state.get("messages", [])
        if msgs:
            last = msgs[-1]
            tcs, _ = _parse_tool_calls(last)
            if tcs:
                return "tools"
        return "end"

    def route_supervisor_agent(state: AgentState) -> str:
        # Guard: if we've delegated too many times, force final response
        if state.get("delegation_count", 0) >= MAX_DELEGATIONS:
            return "end"
        return _route_agent(state, "supervisor_step", "supervisor_finished")

    def route_supervisor_tools(state: AgentState) -> str:
        msgs = state.get("messages", [])
        if msgs:
            for msg in reversed(msgs):
                tcs, _ = _parse_tool_calls(msg)
                if tcs:
                    for tc in tcs:
                        name = tc.get("name", "")
                        if name == "delegate_to_sql_specialist":
                            return "sql_agent"
                        if name == "delegate_to_knowledge_specialist":
                            return "knowledge_agent"
                        if name == "delegate_to_general":
                            return "general_agent"
                    break
        return "response_formatter"

    def route_sql_agent(state: AgentState) -> str:
        return _route_agent(state, "sql_step", "sql_finished")

    def route_knowledge_agent(state: AgentState) -> str:
        return _route_agent(state, "knowledge_step", "knowledge_finished")

    def route_general_agent(state: AgentState) -> str:
        # General agent has no tools — always returns text, never loops
        return "end"

    # ── Edges ──

    builder.add_edge(START, "supervisor_agent")

    # Supervisor loop
    builder.add_conditional_edges("supervisor_agent", route_supervisor_agent, {
        "tools": "supervisor_tools",
        "end": "response_formatter",
    })
    builder.add_conditional_edges("supervisor_tools", route_supervisor_tools, {
        "sql_agent": "sql_agent",
        "knowledge_agent": "knowledge_agent",
        "general_agent": "general_agent",
        "response_formatter": "response_formatter",
    })

    # Increment delegation counter and reset state when specialists return
    async def _specialist_return(state: AgentState) -> dict:
        return {
            "delegation_count": state.get("delegation_count", 0) + 1,
            "supervisor_step": 0, "supervisor_finished": False,
            "sql_step": 0, "sql_finished": False,
            "knowledge_step": 0, "knowledge_finished": False,
        }

    builder.add_node("_specialist_return", _specialist_return)

    # SQL Agent loop → counter → supervisor on finish
    builder.add_conditional_edges("sql_agent", route_sql_agent, {
        "tools": "sql_tools",
        "end": "_specialist_return",
    })
    builder.add_edge("sql_tools", "sql_agent")

    # Knowledge Agent → direct to formatter (search→answer pipeline, no ReAct)
    builder.add_edge("knowledge_agent", "response_formatter")

    # General Agent → always goes to response_formatter (no tools, straight answer)
    builder.add_conditional_edges("general_agent", route_general_agent, {
        "end": "response_formatter",
    })

    # Specialists produce the final answer — route directly to formatter.
    # The Supervisor is a router, not a re-answerer.
    builder.add_edge("_specialist_return", "response_formatter")

    # Terminal
    builder.add_edge("response_formatter", END)

    return builder.compile(checkpointer=MemorySaver())


async def _response_formatter_node(state: AgentState) -> dict:
    """Format the final response — extract last AIMessage text content."""
    msgs = state.get("messages", [])
    final_text = ""

    from langchain_core.messages import AIMessage as AIMsg

    for msg in reversed(msgs):
        if isinstance(msg, AIMsg) and msg.content:
            content = msg.content
            if isinstance(content, str) and content.strip():
                if content.strip().startswith('{"status":'):
                    continue
                final_text = content
                break

    if not final_text:
        final_text = "处理完成。如有其他问题，请继续提问。"

    # Emit structured events: extract SQL blocks from response text
    import re as _re
    sql_match = _re.search(r'```sql\s*\n(.*?)\n```', final_text, _re.DOTALL)
    if sql_match:
        try:
            writer = get_stream_writer()
            sql = sql_match.group(1).strip()
            writer([{"sql": sql}])
        except RuntimeError:
            pass

    return {"final_response": final_text}


# ═══════════════════════════════════════════════════════════════════════════════════
# Agent Runner
# ═══════════════════════════════════════════════════════════════════════════════════

# ── 监控快速路径：关键词匹配直接查询，跳过 LLM ──

_MONITORING_PATTERNS = [
    "连接状态", "连接数", "多少条", "sql在跑", "运行了多久",
    "数据库状态", "慢查询", "连接信息", "数据库连接",
    "多少连接", "活跃查询", "表概况", "运行时间",
]

# Simple greetings that don't need any agent processing
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

    from app.agents.tools.status_tool import GetDatabaseStatusTool
    import json

    tool = GetDatabaseStatusTool(db_connection_id=db_connection_id)
    raw_json = await tool.execute()

    try:
        status_data = json.loads(raw_json)
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
        formatted = f"数据库状态查询结果:\n{raw_json}"

    yield EventEncoder.text_delta(formatted)
    yield EventEncoder.run_finished()


async def run_agent_with_ag_ui(
    user_message: str,
    conversation_id: str,
    model: str,
    db_connection_id: str | None = None,
) -> AsyncIterator[str]:
    """运行 v3 ReAct Agent 并以 AG-UI SSE 流式输出。"""

    # ── 问候快速路径：简单问候直接回复，不经过 Agent ──
    if any(user_message.strip().lower().startswith(p) or user_message.strip() == p for p in _GREETING_PATTERNS):
        async for event in _greeting_fast_path(conversation_id):
            yield event
        return

    # ── 监控快速路径：关键词匹配直接查询数据库状态，跳过 Agent 图 ──
    if any(p in user_message for p in _MONITORING_PATTERNS):
        async for event in _monitoring_fast_path(db_connection_id):
            yield event
        return

    graph = build_graph(db_connection_id=db_connection_id or "")

    # Load conversation history
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

    initial_state: AgentState = {
        "messages": [HumanMessage(content=user_message)],
        "conversation_id": conversation_id,
        "model": model,
        "db_connection_id": db_connection_id,
        "history": history,
        "delegation_count": 0,
        "supervisor_step": 0, "supervisor_finished": False,
        "sql_step": 0, "sql_finished": False,
        "knowledge_step": 0, "knowledge_finished": False,
        "supervisor": {},
        "sql": {},
        "knowledge": {},
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
                            # Preserve error info so frontend can display failure status
                            if "error" in info and "error" not in result:
                                result = {**result, "error": info["error"]} if isinstance(result, dict) else {"error": info["error"]}
                            yield EventEncoder.tool_call_result(info["name"], result)
                        elif "tool_call_end" in ev:
                            info = ev["tool_call_end"]
                            yield EventEncoder.tool_call_end(info.get("name", "unknown"))
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
