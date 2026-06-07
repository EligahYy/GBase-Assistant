"""LangGraph collaborative Agent state definitions.

使用 TypedDict 定义，兼容 LangGraph StateGraph 的 state schema。
所有字段 total=False，Agent 只读写自己的 namespace。
"""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class SupervisorState(TypedDict, total=False):
    """Supervisor-specific state."""

    pending_tasks: list[dict]
    completed_tasks: list[dict]
    active_task: dict | None


class SQLAgentState(TypedDict, total=False):
    """SQL Agent-specific state."""

    generated_sql: str | None
    grounded_schemas: list
    validation: dict | None
    query_result: dict | None
    execution_error: str | None
    retry_count: int
    phase: str


class KnowledgeAgentState(TypedDict, total=False):
    """Knowledge Agent-specific state."""

    knowledge_sources: list[str]
    answer: str | None


class AgentState(TypedDict, total=False):
    """Top-level Agent state — namespace-isolated per-agent state.

    Supervisor writes to state["supervisor"], SQL Agent to state["sql"],
    Knowledge Agent to state["knowledge"]. Cross-agent communication
    happens via messages, not direct state mutation.
    """

    messages: Annotated[list, add_messages]
    supervisor: SupervisorState
    sql: SQLAgentState
    knowledge: KnowledgeAgentState
    final_response: str | None
    supervisor_step: int   # Iteration counter for supervisor agent
    supervisor_finished: bool  # Per-agent finish flag
    sql_step: int          # Iteration counter for SQL agent
    sql_finished: bool     # Per-agent finish flag
    general_step: int       # Iteration counter for general agent
    general_finished: bool  # Per-agent finish flag
    db_connection_id: str | None
