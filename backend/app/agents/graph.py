"""LangGraph 图构建和运行 — v3 ReAct Multi-Agent + token 级流式输出。

所有 Agent 节点内联到主图中（非编译子图），确保 get_stream_writer()
的 custom events 正确传播到 AG-UI SSE 流。
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

from app.agents.agents.general_agent import get_general_agent_prompt
from app.agents.agents.sql_agent import get_sql_agent_prompt, get_sql_agent_tools
from app.agents.agents.supervisor import get_supervisor_prompt, get_supervisor_tools
from app.agents.state import AgentState
from app.agents.tools.sql_tools import ExecuteSQLTool
from app.gateway.ag_ui_encoder import EventEncoder
from app.llm.adapter import LiteLLMChatAdapter

logger = logging.getLogger(__name__)

MAX_PLANNED_TASKS = 3
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
            # Keep persisted conversation through the current user turn, excluding
            # the Supervisor's delegation tool call and its tool result.
            last_user_index = max(
                (idx for idx, message in enumerate(msgs) if isinstance(message, HumanMessage)),
                default=-1,
            )
            msgs = msgs[: last_user_index + 1] if last_user_index >= 0 else msgs

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
        state_update: dict[str, Any] = {}
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
                if agent_name == "sql_agent":
                    sql_state = {**state.get("sql", {})}
                    if tool_name == "search_schemas":
                        sql_state["grounded_schemas"] = result
                    elif tool_name == "submit_sql":
                        sql_state.update({
                            "generated_sql": result.get("sql", "") if isinstance(result, dict) else "",
                            "phase": "proposed",
                        })
                    state_update["sql"] = sql_state
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

        return {"messages": tool_messages, **state_update}

    return node_fn


# ═══════════════════════════════════════════════════════════════════════════════════
# Knowledge Agent — search→answer pipeline (NOT ReAct, no tools for LLM)
# ═══════════════════════════════════════════════════════════════════════════════════

# ── Knowledge retrieval prompt ─────────────────────────────────────────────────────

V3_QA_SYSTEM = """你是 GBase 8a 数据库专家助手。根据以下知识库内容回答用户问题。

## 知识库内容
{knowledge_section}

## 回答规则

1. **基于知识库回答**：只使用上方"知识库内容"中的信息。如果相关内容充分，直接回答。
2. **注明来源**：每条信息注明来自哪个文档（[文档名称]）。
3. **代码示例**：用 ```sql 代码块格式化。
4. **部分相关**：如果知识库内容部分相关，指出哪些有依据、哪些是推测。
5. **不相关**：如果知识库内容与问题无关或信息不足，诚实说"知识库中未找到该信息"。
6. **严禁编造**：不要编造知识库中没有的功能、语法、版本号或参数。
7. **多段引用**：如果多个来源回答了问题的不同方面，综合呈现。
8. **保持简洁**：直接回答问题，不需要额外说明搜索过程。
"""


_KNOWLEDGE_QUERY_EXPANSIONS = {
    "创建": "table_options CREATE TABLE 随机分布表 DDL 建表语句",
    "分布": "分布表 分布方式 DISTRIBUTED 随机分布 HASH",
    "分区": "分区表 分区键 PARTITION CREATE TABLE",
    "随机": "随机分布 RANDOM DISTRIBUTION 分布表",
    "hash": "HASH 哈希 分布键 分布表 随机分布",
}


def _expand_knowledge_query(query: str) -> str:
    """Append domain terms found inside a natural-language query."""
    lowered = query.lower()
    expansions = [
        expansion
        for term, expansion in _KNOWLEDGE_QUERY_EXPANSIONS.items()
        if term in lowered
    ]
    return f"{query} {' '.join(expansions)}".strip() if expansions else query


def _merge_knowledge_chunks(*groups: list[Any], limit: int = 5) -> list[Any]:
    merged = []
    seen = set()
    for group in groups:
        for chunk in group:
            key = f"{chunk.source}|{' '.join(chunk.content.split())[:240]}"
            if key in seen:
                continue
            seen.add(key)
            merged.append(chunk)
            if len(merged) >= limit:
                return merged
    return merged


def _make_knowledge_node(model: Any):
    """Knowledge agent: auto-search → LLM formats answer (v3 approach).

    Design:
    - HybridKnowledgeRetriever: Qdrant vector + ripgrep + RRF fusion
    - Keyword fallback: auto-extract domain terms and retry if results sparse
    - Better prompt: source citation, multi-source synthesis, clear fallback
    - No tool calls exposed to LLM, no ReAct loop
    """

    async def node_fn(state: AgentState) -> dict:
        from app.dependencies import get_knowledge_retriever

        _emit("step_started", {"agent_name": "knowledge_agent", "step_index": 0})

        msgs = state.get("messages", [])
        user_msg = None
        for m in reversed(msgs):
            if isinstance(m, HumanMessage):
                user_msg = m.content if hasattr(m, "content") else str(m)
                break
        if not user_msg:
            user_msg = str(msgs[-1].content) if msgs else ""

        # ── Phase 1: Auto-search with v3 hybrid retriever ──
        _emit("thinking_start", {})
        _emit("thinking_delta", "检索 GBase 8a 知识库")
        _emit("thinking_end", {})

        retriever = get_knowledge_retriever()
        chunks = await retriever.retrieve(user_msg)

        # Domain expansion improves exact fallback and gives vector retrieval extra GBase terminology.
        expanded_query = _expand_knowledge_query(str(user_msg))
        if expanded_query != user_msg:
            expanded_chunks = await retriever.retrieve(expanded_query)
            chunks = _merge_knowledge_chunks(expanded_chunks, chunks)

        _emit("tool_call_start", {"name": "search_knowledge", "args": {"query": str(user_msg)[:100]}, "agent_name": "knowledge_agent"})
        _emit("tool_call_result", {"name": "search_knowledge", "result": {"summary": f"检索到 {len(chunks)} 条相关文档"}})
        _emit("tool_call_end", {"name": "search_knowledge"})

        # ── Phase 2: Build knowledge context ──
        knowledge_lines = []
        source_names: list[str] = []
        if chunks:
            seen_sources = set()
            for i, chunk in enumerate(chunks[:5]):
                src = chunk.source or "未知来源"
                dedup_key = chunk.content[:80]
                if dedup_key in seen_sources:
                    continue
                seen_sources.add(dedup_key)
                if src not in source_names:
                    source_names.append(src)
                content = chunk.content[:3000] if chunk.content else ""
                if content:
                    knowledge_lines.append(f"**来源 {i+1}: [{src}]**\n{content}\n")
        knowledge_section = "\n".join(knowledge_lines) if knowledge_lines else "（未找到相关文档）"

        # ── Phase 3: Build grounded answer prompt ──
        prompt_text = V3_QA_SYSTEM.format(knowledge_section=knowledge_section)
        prompt_text += f"\n## 用户问题\n{user_msg}"

        messages = [HumanMessage(content=prompt_text)]

        try:
            response = await _call_llm(model, messages, None)
            _, text = _parse_tool_calls(response)
            answer = text or "知识库中未找到相关信息，建议查阅 GBase 8a 官方手册。"
        except Exception as e:
            logger.error("Knowledge agent LLM call failed: %s", e)
            answer = f"知识检索处理出错: {e}"

        _emit("delta", answer)
        _emit("state_delta", {"path": "sources", "value": {"sources": source_names}})
        _emit("step_finished", {"agent_name": "knowledge_agent"})
        return {
            "knowledge": {"knowledge_sources": source_names, "answer": answer},
            "messages": [AIMessage(content=answer)],
        }

    return node_fn


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
        feedback = (
            "确定性 SQL 验证失败，请修正后重新调用 submit_sql。"
            f"\n错误：{sql_state['execution_error']}"
        )
        if retry_count >= 3:
            final = f"SQL 在 3 次尝试后仍未通过验证：{sql_state['execution_error']}"
            _emit("delta", final)
            return {"sql": sql_state, "sql_finished": True, "messages": [AIMessage(content=final)]}
        return {"sql": sql_state, "messages": [HumanMessage(content=feedback)]}

    return node_fn


def _make_sql_execution_node(db_connection_id: str):
    """Create the deterministic SQL execution gate."""

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
            final = f"SQL 执行失败：{result['error']}"
            _emit("delta", final)
            return {"sql": sql_state, "sql_finished": True, "messages": [AIMessage(content=final)]}

        sql_state.update({
            "phase": "completed",
            "query_result": result,
            "execution_error": None,
        })
        _emit("state_delta", {"path": "result", "value": result})
        final = (
            f"```sql\n{sql}\n```\n\n"
            f"查询完成：共 {result.get('row_count', 0)} 行，耗时 {result.get('execution_time_ms', 0)}ms。"
        )
        _emit("delta", final)
        return {"sql": sql_state, "sql_finished": True, "messages": [AIMessage(content=final)]}

    return node_fn


# ═══════════════════════════════════════════════════════════════════════════════════
# Graph builder
# ═══════════════════════════════════════════════════════════════════════════════════

def build_graph(db_connection_id: str = "", model: str | None = None) -> StateGraph:
    """Build the v3 hybrid collaborative Agent graph.

    Graph structure:
        START → Planner → task queue → specialist → task complete
                                  ├── SQL ReAct → validate gate → execute gate
                                  ├── Knowledge retrieval pipeline
                                  └── General Agent
                             task queue empty → response formatter → END
    """
    from app.dependencies import get_llm_client

    builder = StateGraph(AgentState)

    planner_llm = LiteLLMChatAdapter(get_llm_client(model=model, task_type="intent_classification"))
    sql_llm = LiteLLMChatAdapter(get_llm_client(model=model, task_type="sql_generation"))
    knowledge_llm = LiteLLMChatAdapter(get_llm_client(model=model, task_type="knowledge_qa"))
    general_llm = LiteLLMChatAdapter(get_llm_client(model=model, task_type="general"))

    # ── Node factories (capture db_connection_id in closure) ──

    def _get_supervisor_tools():
        return get_supervisor_tools()

    def _get_sql_tools():
        return get_sql_agent_tools(db_id=db_connection_id)

    def _get_no_tools():
        return []  # General agent has no tools

    # ── Add nodes ──

    builder.add_node("supervisor_agent", _make_agent_node(
        planner_llm, _get_supervisor_tools, get_supervisor_prompt, "supervisor", "supervisor_step", "supervisor_finished"
    ))
    builder.add_node("supervisor_tools", _make_tools_node(_get_supervisor_tools(), "supervisor"))

    builder.add_node("sql_agent", _make_agent_node(
        sql_llm, _get_sql_tools, get_sql_agent_prompt, "sql_agent", "sql_step", "sql_finished",
        isolate_context=True,
    ))
    builder.add_node("sql_tools", _make_tools_node(_get_sql_tools(), "sql_agent"))
    builder.add_node("sql_validate", _make_sql_validation_node())
    builder.add_node("sql_execute", _make_sql_execution_node(db_connection_id))

    # Knowledge Agent: auto-search → LLM formats answer (NOT ReAct — no tools, no loop)
    builder.add_node("knowledge_agent", _make_knowledge_node(knowledge_llm))

    builder.add_node("general_agent", _make_agent_node(
        general_llm, _get_no_tools, get_general_agent_prompt, "general_agent", "general_step", "general_finished",
        isolate_context=True,
    ))

    async def _build_task_plan(state: AgentState) -> dict:
        """Translate Supervisor delegate calls into an explicit specialist task queue."""
        tasks: list[dict] = []
        for message in reversed(state.get("messages", [])):
            tool_calls, _ = _parse_tool_calls(message)
            if not tool_calls:
                continue
            for tool_call in tool_calls:
                task_type = {
                    "delegate_to_sql_specialist": "sql",
                    "delegate_to_knowledge_specialist": "knowledge",
                    "delegate_to_general": "general",
                }.get(tool_call.get("name", ""))
                if task_type:
                    tasks.append({
                        "type": task_type,
                        "query": str(tool_call.get("args", {}).get("query", "")),
                    })
            break
        supervisor_state = {**state.get("supervisor", {})}
        supervisor_state.update({
            "pending_tasks": tasks[:MAX_PLANNED_TASKS],
            "completed_tasks": [],
            "active_task": None,
        })
        return {"supervisor": supervisor_state}

    async def _dispatch_task(state: AgentState) -> dict:
        """Pop one planned task and add its scoped query to the specialist context."""
        supervisor_state = {**state.get("supervisor", {})}
        pending = list(supervisor_state.get("pending_tasks", []))
        if not pending:
            return {"supervisor": supervisor_state}
        active = pending.pop(0)
        supervisor_state.update({"pending_tasks": pending, "active_task": active})
        return {
            "supervisor": supervisor_state,
            "messages": [HumanMessage(content=active.get("query", ""))],
        }

    async def _complete_task(state: AgentState) -> dict:
        """Record specialist output, reset its loop state, and continue the plan."""
        supervisor_state = {**state.get("supervisor", {})}
        completed = list(supervisor_state.get("completed_tasks", []))
        active = supervisor_state.get("active_task") or {}
        answer = ""
        for message in reversed(state.get("messages", [])):
            if isinstance(message, AIMessage) and message.content:
                answer = str(message.content)
                break
        completed.append({**active, "answer": answer})
        supervisor_state.update({"completed_tasks": completed, "active_task": None})
        return {
            "supervisor": supervisor_state,
            "sql_step": 0,
            "sql_finished": False,
            "general_step": 0,
            "general_finished": False,
        }

    builder.add_node("task_plan", _build_task_plan)
    builder.add_node("task_dispatch", _dispatch_task)
    builder.add_node("task_complete", _complete_task)
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
        return _route_agent(state, "supervisor_step", "supervisor_finished")

    def route_task_plan(state: AgentState) -> str:
        return "dispatch" if state.get("supervisor", {}).get("pending_tasks") else "end"

    def route_task_dispatch(state: AgentState) -> str:
        task_type = state.get("supervisor", {}).get("active_task", {}).get("type")
        return task_type if task_type in {"sql", "knowledge", "general"} else "end"

    def route_task_complete(state: AgentState) -> str:
        return "dispatch" if state.get("supervisor", {}).get("pending_tasks") else "end"

    def route_sql_agent(state: AgentState) -> str:
        return _route_agent(state, "sql_step", "sql_finished")

    def route_sql_tools(state: AgentState) -> str:
        if state.get("sql", {}).get("phase") == "proposed":
            return "validate"
        return "agent"

    def route_sql_validation(state: AgentState) -> str:
        sql_state = state.get("sql", {})
        if sql_state.get("validation", {}).get("valid"):
            return "execute"
        if state.get("sql_finished"):
            return "end"
        return "agent"

    # ── Edges ──

    builder.add_edge(START, "supervisor_agent")

    # Supervisor loop
    builder.add_conditional_edges("supervisor_agent", route_supervisor_agent, {
        "tools": "supervisor_tools",
        "end": "response_formatter",
    })
    builder.add_edge("supervisor_tools", "task_plan")
    builder.add_conditional_edges("task_plan", route_task_plan, {
        "dispatch": "task_dispatch",
        "end": "response_formatter",
    })
    builder.add_conditional_edges("task_dispatch", route_task_dispatch, {
        "sql": "sql_agent",
        "knowledge": "knowledge_agent",
        "general": "general_agent",
        "end": "response_formatter",
    })

    # SQL Specialist loop and deterministic gates
    builder.add_conditional_edges("sql_agent", route_sql_agent, {
        "tools": "sql_tools",
        "end": "task_complete",
    })
    builder.add_conditional_edges("sql_tools", route_sql_tools, {
        "validate": "sql_validate",
        "agent": "sql_agent",
    })
    builder.add_conditional_edges("sql_validate", route_sql_validation, {
        "execute": "sql_execute",
        "agent": "sql_agent",
        "end": "task_complete",
    })
    builder.add_edge("sql_execute", "task_complete")

    builder.add_edge("knowledge_agent", "task_complete")

    builder.add_edge("general_agent", "task_complete")
    builder.add_conditional_edges("task_complete", route_task_complete, {
        "dispatch": "task_dispatch",
        "end": "response_formatter",
    })

    # Terminal
    builder.add_edge("response_formatter", END)

    return builder.compile(checkpointer=MemorySaver())


async def _response_formatter_node(state: AgentState) -> dict:
    """Format the final response — extract last AIMessage text content."""
    msgs = state.get("messages", [])
    final_text = ""
    completed_tasks = state.get("supervisor", {}).get("completed_tasks", [])
    if len(completed_tasks) > 1:
        sections = []
        labels = {"sql": "数据查询", "knowledge": "知识说明", "general": "补充回答"}
        for task in completed_tasks:
            answer = str(task.get("answer", "")).strip()
            if answer:
                sections.append(f"### {labels.get(task.get('type'), '任务结果')}\n{answer}")
        final_text = "\n\n".join(sections)

    from langchain_core.messages import AIMessage as AIMsg

    if not final_text:
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
        "supervisor_step": 0, "supervisor_finished": False,
        "sql_step": 0, "sql_finished": False,
        "general_step": 0, "general_finished": False,
        "supervisor": {},
        "sql": {"retry_count": 0, "phase": "idle"},
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
