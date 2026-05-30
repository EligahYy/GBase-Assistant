"""LangGraph 图构建和运行 — v2 多智能体 + token 级流式输出。"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver
from langgraph.config import get_stream_writer

from app.agents.orchestrator import classify_intent_v2, route_after_intent, supervisor_check_node
from app.agents.semantic_mapper import semantic_mapper_node
from app.agents.schema_graph import get_schema_graph, SchemaGraph
from app.agents.state import AgentStateType
from app.gateway.ag_ui_encoder import EventEncoder

logger = logging.getLogger(__name__)


def _last_user_message(state: AgentStateType) -> str:
    msgs = state.get("messages", [])
    if msgs:
        last = msgs[-1]
        if hasattr(last, "content"):
            content = last.content
            if isinstance(content, str):
                return content
        if isinstance(last, dict):
            return last.get("content", "")
    return ""


# ── 流式辅助 ──

def _emit_token(token: str) -> None:
    """通过 LangGraph StreamWriter 发射一个 token 作为自定义事件。"""
    writer = get_stream_writer()
    # 包在 list 里防止 StreamWriter 把字符串逐字符迭代
    writer([{"delta": token}])


# ── Agent 节点 ──

async def orchestrator_node(state: AgentStateType) -> dict:
    user_msg = _last_user_message(state)
    intent = classify_intent_v2(user_msg)
    logger.info("Orchestrator: intent=%s for '%s'", intent, user_msg[:50])
    return {"intent": intent}


async def schema_grounding_node(state: AgentStateType) -> dict:
    user_msg = _last_user_message(state)
    db_id = state.get("db_connection_id")
    if not db_id:
        return {"grounding": None}

    graph = get_schema_graph(db_id)
    if not graph._built:
        loaded = SchemaGraph.load(db_id)
        if loaded:
            from app.agents.schema_graph import _graph_instances
            _graph_instances[db_id] = loaded
            graph = loaded
        else:
            return {"grounding": None}

    matches = graph.exact_match(user_msg)
    if not matches:
        return {"grounding": {"tables": [], "columns": {}, "join_paths": [], "confidence": 0.0}}

    table_hits: dict[str, set] = {}
    column_hits: dict[str, list[str]] = {}
    for m in matches:
        table = m["table"]
        if table not in table_hits:
            table_hits[table] = set()
            column_hits[table] = []
        if m["column"] != "*":
            table_hits[table].add(m["column"])
            column_hits[table].append(m["column"])

    table_list = list(table_hits.keys())
    join_paths: list[str] = []
    if len(table_list) > 1:
        for i in range(len(table_list)):
            for j in range(i + 1, len(table_list)):
                path = graph.find_join_path(table_list[i], table_list[j])
                if path:
                    for rel in path:
                        if rel["via"] not in join_paths:
                            join_paths.append(rel["via"])

    confidence = min(0.9, 0.5 + len(matches) * 0.1)
    return {"grounding": {
        "tables": table_list,
        "columns": {t: list(c) for t, c in column_hits.items()},
        "join_paths": join_paths,
        "confidence": round(confidence, 2),
        "matches": len(matches),
    }}


async def sql_specialist_node(state: AgentStateType) -> dict:
    from app.dependencies import get_llm_client, get_schema_retriever
    from app.llm.prompts import build_sql_prompt
    from app.knowledge.loader import load_dialect_rules
    from app.sql.validator import extract_sql_from_markdown
    from app.database import async_session_factory

    grounding = state.get("grounding") or {}
    user_msg = _last_user_message(state)

    try:
        llm_client = get_llm_client(task_type="sql")
        dialect_rules = load_dialect_rules()

        schemas: list = []
        if state.get("db_connection_id"):
            async with async_session_factory() as session:
                schema_retriever = get_schema_retriever(session)
                schemas = await schema_retriever.retrieve(user_msg, state["db_connection_id"])

        grounded_tables = set(grounding.get("tables", []))

        # Use grounded tables as a hint but DON'T filter — trust the vector search
        # and let the prompt's business_terms guide the LLM

        # Fetch few-shot examples
        examples_list: list = []
        try:
            from app.dependencies import get_example_retriever
            example_retriever = get_example_retriever()
            if example_retriever:
                examples_list = await example_retriever.retrieve(user_msg, top_k=3)
        except Exception:
            pass

        business_terms = state.get("business_terms")
        chart_config_hint = state.get("chart_config")

        messages = build_sql_prompt(
            message=user_msg, dialect_rules=dialect_rules,
            schemas=schemas, examples=examples_list, history=[],
            business_terms=business_terms,
            chart_config=chart_config_hint,
        )

        response_text = ""
        async for token in llm_client.stream(messages, temperature=0.1):
            response_text += token
            _emit_token(token)

        sql = extract_sql_from_markdown(response_text)
        logger.info("SQL Specialist: generated SQL=%s", sql[:100] if sql else "None")
        return {"generated_sql": sql}
    except Exception as e:
        logger.error("SQL Specialist failed: %s", e)
        return {"generated_sql": None, "final_response": f"SQL 生成失败: {e}"}


async def sql_verifier_node(state: AgentStateType) -> dict:
    from app.sql.validator import validate_sql
    sql = state.get("generated_sql")
    if not sql:
        return {"validation_passed": False, "validation_errors": ["未生成 SQL"]}

    # Build schemas for Layer 3 cross-reference check
    schemas_arg = None
    grounding = state.get("grounding") or {}
    tables_list = grounding.get("tables", [])
    if tables_list and state.get("db_connection_id"):
        from app.agents.schema_graph import get_schema_graph
        g = get_schema_graph(state["db_connection_id"])
        if g._built:
            schemas_arg = []
            for t in tables_list:
                if t in g.tables:
                    meta = g.tables[t]
                    schemas_arg.append({"table_name": t, "columns": [{"name": c.name, "type": c.data_type} for c in meta.columns]})

    result = validate_sql(sql, schemas=schemas_arg)
    logger.info("SQL Verifier: passed=%s", result.is_valid)
    retry = state.get("sql_retry_count", 0)
    return {
        "validation_passed": result.is_valid,
        "validation_errors": result.errors + result.warnings,
        "sql_retry_count": retry + 1,
    }


async def sql_executor_node(state: AgentStateType) -> dict:
    from app.database import async_session_factory
    from sqlalchemy import select
    from app.models.connection import DbConnection
    from app.db_connectors.connector_factory import get_connector
    from app.api.connections import _to_connection_config
    from app.sql.sandbox import SQLSandbox, SQLSandboxError

    sql = state.get("generated_sql")
    db_id = state.get("db_connection_id")
    if not sql or not db_id:
        return {"query_result": None, "execution_error": "没有 SQL 或数据库连接"}

    try:
        async with async_session_factory() as session:
            result = await session.execute(select(DbConnection).where(DbConnection.id == db_id))
            conn = result.scalar_one_or_none()
        if not conn or conn.driver_type == "manual":
            return {"query_result": None, "execution_error": "数据库连接不可用"}

        connector = get_connector(conn.driver_type)
        if not connector:
            return {"query_result": None, "execution_error": f"驱动 {conn.driver_type} 不可用"}

        config = _to_connection_config(conn)
        sandbox = SQLSandbox()
        query_result = await sandbox.execute_readonly(connector, config, sql, max_rows=1000, timeout_seconds=30)

        return {"query_result": {
            "columns": query_result.columns, "rows": query_result.rows[:50],
            "row_count": query_result.row_count,
            "execution_time_ms": round(query_result.execution_time_ms, 2),
            "truncated": query_result.truncated or query_result.row_count > 50,
        }, "execution_error": None}
    except SQLSandboxError as e:
        return {"query_result": None, "execution_error": str(e)}
    except Exception as e:
        logger.error("SQL Executor failed: %s", e)
        return {"query_result": None, "execution_error": str(e)}


async def knowledge_specialist_node(state: AgentStateType) -> dict:
    from app.dependencies import get_llm_client, get_knowledge_retriever
    from app.llm.prompts import build_qa_prompt

    user_msg = _last_user_message(state)
    if not user_msg:
        return {"final_response": "请输入问题。"}

    try:
        llm_client = get_llm_client(task_type="qa")
        retriever = get_knowledge_retriever()
        chunks = await retriever.retrieve(user_msg)
        messages = build_qa_prompt(message=user_msg, knowledge_chunks=chunks, history=[])

        response_text = ""
        async for token in llm_client.stream(messages):
            response_text += token
            _emit_token(token)

        sources = [c.source for c in chunks] if chunks else []
        return {"final_response": response_text, "knowledge_sources": sources}
    except Exception as e:
        logger.error("Knowledge Specialist failed: %s", e)
        return {"final_response": f"知识检索失败: {e}"}


async def general_specialist_node(state: AgentStateType) -> dict:
    from app.dependencies import get_llm_client
    from app.llm.prompts import build_general_prompt

    user_msg = _last_user_message(state)
    if not user_msg:
        # 硬编码兜底：无 streaming，直接返回文本
        return {"final_response": "您好！请问有什么可以帮您？"}

    try:
        llm_client = get_llm_client(task_type="general")
        messages = build_general_prompt(message=user_msg, history=[])

        response_text = ""
        async for token in llm_client.stream(messages):
            response_text += token
            _emit_token(token)

        return {"final_response": response_text}
    except Exception as e:
        logger.error("General Specialist failed: %s", e)
        return {"final_response": f"抱歉，出错了: {e}"}


async def response_formatter_node(state: AgentStateType) -> dict:
    intent = state.get("intent", "general")
    final_response = state.get("final_response", "")

    if intent == "sql" and not final_response:
        writer = get_stream_writer()

        # Emit chart_config event
        chart_config_data = state.get("chart_config")
        if chart_config_data:
            writer([{"chart_config": chart_config_data}])

        sql = state.get("generated_sql")
        if sql:
            writer([{"sql": sql}])

        query_result = state.get("query_result")
        if query_result:
            writer([{"result": query_result}])

        validation_errors = state.get("validation_errors", [])
        exec_error = state.get("execution_error")

        parts = []
        if sql:
            parts.append(f"```sql\n{sql}\n```")
        if validation_errors:
            parts.append(f"\n⚠️ 验证警告: {', '.join(validation_errors)}")
        if query_result:
            parts.append(f"\n查询结果: {query_result['row_count']} 行, 耗时 {query_result['execution_time_ms']}ms")
        if exec_error:
            parts.append(f"\n执行错误: {exec_error}")
        if not parts:
            parts.append("SQL 生成完成，但未获得有效结果。")
        final_response = "\n".join(parts)

    if not final_response:
        final_response = "处理完成。"

    return {"final_response": final_response}


async def ask_user_clarification_node(state: AgentStateType) -> dict:
    """Ask user to clarify when confidence is too low or schema validation fails."""
    clarification = state.get("needs_clarification", "无法理解您的问题，请提供更多信息。")
    return {"final_response": clarification}


# ── 图构建 ──

def build_graph() -> StateGraph:
    builder = StateGraph(AgentStateType)

    builder.add_node("orchestrator", orchestrator_node)
    builder.add_node("semantic_mapper", semantic_mapper_node)
    builder.add_node("supervisor_check", supervisor_check_node)
    builder.add_node("ask_user_clarification", ask_user_clarification_node)
    builder.add_node("sql_specialist", sql_specialist_node)
    builder.add_node("sql_verifier", sql_verifier_node)
    builder.add_node("sql_executor", sql_executor_node)
    builder.add_node("knowledge_specialist", knowledge_specialist_node)
    builder.add_node("general_specialist", general_specialist_node)
    builder.add_node("response_formatter", response_formatter_node)

    builder.add_edge(START, "orchestrator")

    # Route based on intent
    builder.add_conditional_edges(
        "orchestrator", route_after_intent,
        {"semantic_mapper": "semantic_mapper", "knowledge_specialist": "knowledge_specialist",
         "general_specialist": "general_specialist", "response_formatter": "response_formatter"},
    )

    # SQL path: semantic_mapper → supervisor_check → (sql_specialist | ask_user_clarification)
    builder.add_edge("semantic_mapper", "supervisor_check")

    def route_after_supervisor(state: AgentStateType) -> str:
        if state.get("needs_clarification"):
            return "ask_user_clarification"
        return "sql_specialist"

    builder.add_conditional_edges(
        "supervisor_check", route_after_supervisor,
        {"sql_specialist": "sql_specialist", "ask_user_clarification": "ask_user_clarification"},
    )
    builder.add_edge("ask_user_clarification", END)

    # Existing SQL specialist → verifier → executor path
    builder.add_edge("sql_specialist", "sql_verifier")

    def route_verifier(state: AgentStateType) -> str:
        if state.get("validation_passed"):
            return "sql_executor"
        if state.get("sql_retry_count", 0) < 3:
            return "sql_specialist"
        return "response_formatter"

    builder.add_conditional_edges(
        "sql_verifier", route_verifier,
        {"sql_executor": "sql_executor", "sql_specialist": "sql_specialist", "response_formatter": "response_formatter"},
    )

    builder.add_edge("sql_executor", "response_formatter")
    builder.add_edge("knowledge_specialist", "response_formatter")
    builder.add_edge("general_specialist", "response_formatter")
    builder.add_edge("response_formatter", END)

    return builder.compile(checkpointer=MemorySaver())


# ── Agent Runner（AG-UI 流式输出） ──

async def run_agent_with_ag_ui(
    user_message: str,
    conversation_id: str,
    model: str,
    db_connection_id: str | None = None,
) -> AsyncIterator[str]:
    """运行 LangGraph Agent 并以 AG-UI token 级流式 SSE 输出。"""
    graph = build_graph()

    initial_state: AgentStateType = {
        "messages": [{"role": "user", "content": user_message}],
        "conversation_id": conversation_id,
        "model": model,
        "db_connection_id": db_connection_id,
    }

    yield EventEncoder.run_started(conversation_id)

    config = {"configurable": {"thread_id": conversation_id}}
    streamed_text = False

    try:
        async for mode, events in graph.astream(initial_state, config=config, stream_mode=["custom", "updates"]):
            if mode == "custom":
                for ev in events:
                    if isinstance(ev, dict):
                        if "delta" in ev:
                            yield EventEncoder.text_delta(ev["delta"])
                            streamed_text = True
                        elif "sql" in ev:
                            yield EventEncoder.sql_event(ev["sql"])
                        elif "chart_config" in ev:
                            yield EventEncoder.chart_config(ev["chart_config"])
                        elif "result" in ev:
                            yield EventEncoder.result_event(ev["result"])

        # 获取最终状态
        final_state = await graph.aget_state(config)
        state_values = final_state.values if final_state else {}
        response = state_values.get("final_response", "") if state_values else ""

        # 如果没有流式输出（硬编码兜底、SQL 格式化结果等），发送完整文本
        if response and not streamed_text:
            yield EventEncoder.text_delta(response)

        yield EventEncoder.run_finished()

    except Exception as e:
        logger.error("Agent run failed: %s", e)
        yield EventEncoder.run_error(str(e))
