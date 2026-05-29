"""LangGraph 图构建和运行。

Phase 1: 搭建完整图结构，Specialist 节点为 stub 实现。
Phase 3: 替换所有 stub 为真实 Agent 实现（SQL 生成、知识问答、通用对话）。
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from typing import TYPE_CHECKING

from langgraph.graph import StateGraph, START, END
from langgraph.checkpoint.memory import MemorySaver

from app.agents.orchestrator import classify_intent_v2, route_after_intent
from app.agents.schema_graph import get_schema_graph, SchemaGraph
from app.agents.state import AgentStateType
from app.gateway.ag_ui_encoder import EventEncoder

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


def _last_user_message(state: AgentStateType) -> str:
    """从 state 中提取最后一条用户消息。"""
    msgs = state.get("messages", [])
    if msgs:
        last = msgs[-1]
        # LangGraph add_messages reducer converts dicts to LangChain message objects
        if hasattr(last, "content"):
            content = last.content
            if isinstance(content, str):
                return content
        if isinstance(last, dict):
            return last.get("content", "")
    return ""


# ── Agent 节点 ──
# Orchestrator: 意图分类
# Schema Grounding: Schema 检索
# SQL Specialist: 基于 LLM 的 GBase SQL 生成
# SQL Verifier: 语法/方言/Schema 交叉验证
# SQL Executor: 沙箱安全执行
# Knowledge Specialist: RAG 知识问答
# General Specialist: 通用对话
# Response Formatter: 汇聚所有结果构建最终响应

async def orchestrator_node(state: AgentStateType) -> dict:
    """Orchestrator: 分类意图，记录到 state。"""
    user_msg = _last_user_message(state)
    intent = classify_intent_v2(user_msg)
    state["intent"] = intent
    logger.info("Orchestrator: classified intent=%s for message='%s'", intent, user_msg[:50])
    return {"intent": intent}


async def schema_grounding_node(state: AgentStateType) -> dict:
    """Schema Grounding: 多策略检索定位用户问题涉及的表和列。"""
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
    grounding = {
        "tables": table_list,
        "columns": {t: list(c) for t, c in column_hits.items()},
        "join_paths": join_paths,
        "confidence": round(confidence, 2),
        "matches": len(matches),
    }
    return {"grounding": grounding}


async def sql_specialist_node(state: AgentStateType) -> dict:
    """SQL Specialist: 基于 Grounding 结果生成 GBase SQL。"""
    from app.dependencies import get_llm_client, get_schema_retriever
    from app.llm.prompts import build_sql_prompt
    from app.knowledge.loader import load_dialect_rules
    from app.sql.validator import extract_sql_from_markdown
    from app.database import async_session_factory

    grounding = state.get("grounding") or {}
    user_msg = _last_user_message(state)

    try:
        llm_client = get_llm_client()
        dialect_rules = load_dialect_rules()

        schemas: list = []
        if state.get("db_connection_id"):
            async with async_session_factory() as session:
                schema_retriever = get_schema_retriever(session)
                schemas = await schema_retriever.retrieve(
                    user_msg, state["db_connection_id"]
                )

        # Filter to only grounded tables
        grounded_tables = set(grounding.get("tables", []))
        if grounded_tables and schemas:
            filtered = [s for s in schemas if s.table_name in grounded_tables]
            if filtered:
                schemas = filtered

        messages = build_sql_prompt(
            message=user_msg,
            dialect_rules=dialect_rules,
            schemas=schemas,
            examples=[],
            history=[],
        )

        response_text, usage = await llm_client.complete(messages, temperature=0.1)
        sql = extract_sql_from_markdown(response_text)

        logger.info("SQL Specialist: generated SQL=%s", sql[:100] if sql else "None")
        return {
            "generated_sql": sql,
            "stream_buffer": [response_text],
        }
    except Exception as e:
        logger.error("SQL Specialist failed: %s", e)
        return {
            "generated_sql": None,
            "final_response": f"SQL 生成失败: {e}",
        }


async def sql_verifier_node(state: AgentStateType) -> dict:
    """SQL Verifier: 三层验证（语法/方言/Schema交叉）。"""
    from app.sql.validator import validate_sql

    sql = state.get("generated_sql")

    if not sql:
        return {"validation_passed": False, "validation_errors": ["未生成 SQL"]}

    result = validate_sql(sql, schemas=None)

    passed = result.is_valid
    errors = result.errors + result.warnings

    logger.info("SQL Verifier: passed=%s, errors=%s", passed, errors)
    retry = state.get("sql_retry_count", 0)
    return {
        "validation_passed": passed,
        "validation_errors": errors,
        "sql_retry_count": retry + 1,
    }


async def sql_executor_node(state: AgentStateType) -> dict:
    """SQL Executor: 沙箱执行 SQL。"""
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
            result = await session.execute(
                select(DbConnection).where(DbConnection.id == db_id)
            )
            conn = result.scalar_one_or_none()

        if not conn or conn.driver_type == "manual":
            return {"query_result": None, "execution_error": "数据库连接不可用"}

        connector = get_connector(conn.driver_type)
        if not connector:
            return {"query_result": None, "execution_error": f"驱动 {conn.driver_type} 不可用"}

        config = _to_connection_config(conn)
        sandbox = SQLSandbox()
        query_result = await sandbox.execute_readonly(
            connector, config, sql, max_rows=1000, timeout_seconds=30,
        )

        result_dict = {
            "columns": query_result.columns,
            "rows": query_result.rows[:50],
            "row_count": query_result.row_count,
            "execution_time_ms": round(query_result.execution_time_ms, 2),
            "truncated": query_result.truncated or query_result.row_count > 50,
        }
        return {"query_result": result_dict, "execution_error": None}

    except SQLSandboxError as e:
        return {"query_result": None, "execution_error": str(e)}
    except Exception as e:
        logger.error("SQL Executor failed: %s", e)
        return {"query_result": None, "execution_error": str(e)}


async def knowledge_specialist_node(state: AgentStateType) -> dict:
    """Knowledge Specialist: RAG 知识问答。"""
    from app.dependencies import get_llm_client, get_knowledge_retriever
    from app.chains.qa_chain import run_qa_chain
    from app.protocols import ChatContext

    user_msg = _last_user_message(state)

    if not user_msg:
        return {"final_response": "请输入问题。"}

    try:
        llm_client = get_llm_client()
        retriever = get_knowledge_retriever()
        context = ChatContext(history=[])
        result = await run_qa_chain(user_msg, context, retriever, llm_client)

        return {
            "final_response": result.content,
            "knowledge_sources": result.sources,
        }
    except Exception as e:
        logger.error("Knowledge Specialist failed: %s", e)
        return {"final_response": f"知识检索失败: {e}"}


async def general_specialist_node(state: AgentStateType) -> dict:
    """General Specialist: 通用对话。"""
    from app.dependencies import get_llm_client
    from app.llm.prompts import build_general_prompt

    user_msg = _last_user_message(state)

    if not user_msg:
        return {"final_response": "您好！请问有什么可以帮您？"}

    try:
        llm_client = get_llm_client()
        messages = build_general_prompt(message=user_msg, history=[])
        response_text, _ = await llm_client.complete(messages)
        return {"final_response": response_text}
    except Exception as e:
        logger.error("General Specialist failed: %s", e)
        return {"final_response": f"抱歉，出错了: {e}"}


async def response_formatter_node(state: AgentStateType) -> dict:
    """Response Formatting: 汇聚所有结果构建最终响应。"""
    intent = state.get("intent", "general")
    final_response = state.get("final_response", "")

    if intent == "sql" and not final_response:
        sql = state.get("generated_sql")
        query_result = state.get("query_result")
        validation_errors = state.get("validation_errors", [])
        exec_error = state.get("execution_error")

        parts = []
        if sql:
            parts.append(f"```sql\n{sql}\n```")
        if validation_errors:
            parts.append(f"\n⚠️ 验证警告: {', '.join(validation_errors)}")
        if query_result:
            parts.append(f"\n查询结果: {query_result['row_count']} 行, "
                        f"耗时 {query_result['execution_time_ms']}ms")
        if exec_error:
            parts.append(f"\n执行错误: {exec_error}")
        if not parts:
            parts.append("SQL 生成完成，但未获得有效结果。")

        final_response = "\n".join(parts)
        return {"final_response": final_response}

    if not final_response:
        final_response = "处理完成。"

    return {"final_response": final_response}


# ── 图构建 ──

def build_graph() -> StateGraph:
    """构建 LangGraph StateGraph。

    Phase 3: 所有 Specialist 节点已替换为真实 Agent 调用。
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
    builder.add_conditional_edges(
        "orchestrator",
        route_after_intent,
        {
            "schema_grounding": "schema_grounding",
            "knowledge_specialist": "knowledge_specialist",
            "general_specialist": "general_specialist",
            "response_formatter": "response_formatter",
        },
    )

    # SQL 路径: grounding → specialist → verifier → executor → response
    builder.add_edge("schema_grounding", "sql_specialist")
    builder.add_edge("sql_specialist", "sql_verifier")

    # Verifier 条件路由
    def route_verifier(state: AgentStateType) -> str:
        if state.get("validation_passed"):
            return "sql_executor"
        retry = state.get("sql_retry_count", 0)
        if retry < 3:
            return "sql_specialist"
        return "response_formatter"

    builder.add_conditional_edges(
        "sql_verifier",
        route_verifier,
        {
            "sql_executor": "sql_executor",
            "sql_specialist": "sql_specialist",
            "response_formatter": "response_formatter",
        },
    )

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

    # Checkpointer 需要 thread_id
    config = {"configurable": {"thread_id": conversation_id}}

    try:
        # 使用 astream_events 获取节点级别的执行流
        prev_node: str | None = None
        async for event in graph.astream_events(initial_state, config=config, version="v2"):
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

        # 获取最终状态（从 checkpointer 读取，不重新执行）
        final_state = await graph.aget_state(config)
        state_values = final_state.values if final_state else {}
        response = state_values.get("final_response", "") if state_values else ""
        if response:
            yield EventEncoder.text_delta(response)

        # RUN_FINISHED
        yield EventEncoder.run_finished()

    except Exception as e:
        logger.error("Agent run failed: %s", e)
        yield EventEncoder.run_error(str(e))
