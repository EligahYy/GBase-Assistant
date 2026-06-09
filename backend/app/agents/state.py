"""LangGraph collaborative Agent state definitions — v3.2 Unified Agent.

Uses TypedDict for LangGraph StateGraph compatibility.
All fields total=False — agents only read/write their own namespace.
"""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class SQLAgentState(TypedDict, total=False):
    """SQL Agent-specific state — minimal tracking for schema grounding."""

    grounded_schemas: list  # Schema exploration results for the validator


class KnowledgeAgentState(TypedDict, total=False):
    """Knowledge pipeline state."""

    knowledge_sources: list[str]
    answer: str | None
    status: str  # found | partial | not_found


class AgentState(TypedDict, total=False):
    """Top-level Agent state — v3.2 unified fields.

    Unified agent reads/writes to state["messages"] and state["sql"].
    Knowledge pipeline writes to state["knowledge"].
    Cross-agent communication via messages, not direct state mutation.
    """

    messages: Annotated[list, add_messages]
    sql: SQLAgentState
    knowledge: KnowledgeAgentState
    final_response: str | None
    agent_step: int       # Unified iteration counter
    agent_finished: bool  # Unified finish flag (set by final_answer or termination)
    db_connection_id: str | None
