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
from app.agents.schema_graph import get_schema_graph, SchemaGraph
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
    logger.info("Orchestrator: classified intent=%s for message='%s'", intent, user_msg[:50])
    return {"intent": intent}


async def schema_grounding_node(state: AgentStateType) -> dict:
    """Schema Grounding: 多策略检索定位用户问题涉及的表和列。"""
    user_msg = ""
    msgs = state.get("messages", [])
    if msgs:
        last = msgs[-1]
        if isinstance(last, dict):
            user_msg = last.get("content", "")

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
    """SQL Specialist stub: Phase 3 实现。"""
    return {
        "generated_sql": None,
        "final_response": "SQL 生成功能将在 Phase 3 实现。您的问题已识别为数据查询意图。"
    }


async def sql_verifier_node(state: AgentStateType) -> dict:
    """SQL Verifier stub: Phase 3 实现。"""
    return {"validation_passed": True, "validation_errors": []}


async def sql_executor_node(state: AgentStateType) -> dict:
    """SQL Executor stub: Phase 3 实现。"""
    return {"query_result": None, "execution_error": None}


async def knowledge_specialist_node(state: AgentStateType) -> dict:
    """Knowledge Specialist stub: Phase 3 实现。"""
    return {"final_response": "知识问答功能将在 Phase 3 实现。您的问题已识别为知识查询意图。"}


async def general_specialist_node(state: AgentStateType) -> dict:
    """General Specialist stub: Phase 3 实现。"""
    return {
        "final_response": (
            "您好！我是 GBase 8a 助手。\n\n"
            "目前支持的功能将在后续版本中上线，包括：\n"
            "- SQL 生成：自然语言转 GBase 8a SQL\n"
            "- 知识问答：GBase 8a 语法、配置、错误码查询\n"
            "- 数据库查询：连接您的 GBase 数据库直接执行查询\n\n"
            "敬请期待！"
        )
    }


async def response_formatter_node(state: AgentStateType) -> dict:
    """Response Formatting: 汇聚最终响应。"""
    return {}


# ── 图构建 ──

def build_graph() -> StateGraph:
    """构建 LangGraph StateGraph。

    Phase 1: 完整图结构，stub 节点。
    Phase 3: 替换 stub 为真实 Agent 调用。
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
            state["sql_retry_count"] = retry + 1
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

        # 获取最终状态
        final_state = await graph.ainvoke(initial_state, config=config)
        response = final_state.get("final_response", "")
        if response:
            yield EventEncoder.text_delta(response)

        # RUN_FINISHED
        yield EventEncoder.run_finished()

    except Exception as e:
        logger.error("Agent run failed: %s", e)
        yield EventEncoder.run_error(str(e))
