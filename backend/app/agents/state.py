"""Typed state contract for the v3.4 semantic NL2SQL graph."""

from __future__ import annotations

from typing import Annotated, Any, TypedDict

from langchain_core.messages import BaseMessage
from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """Fields are merged by LangGraph instead of replacing the whole state."""

    messages: Annotated[list[BaseMessage], add_messages]
    db_connection_id: str | None
    resolved_question: str
    semantic_context: Any
    query_ir: dict[str, Any]
    should_clarify: bool
    planning_error: str
    sql_candidate: str
    sql_history: list[dict[str, Any]]
    validation_report: dict[str, Any]
    should_retry: bool
    retry_hint: str
    execution_count: int
    query_result: dict[str, Any]
    final_response: str
    semantic_logic: str

    # Compatibility namespaces retained for persisted/legacy callers.
    supervisor: dict[str, Any]
    sql: dict[str, Any]
    knowledge: dict[str, Any]
