"""LangGraph Agent state definitions — v3.3 Circuit Breaker ReAct.

Three-phase architecture (explore → sql → answer) with deterministic
circuit breaker signals for safe termination.
"""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class ExploreState(TypedDict, total=False):
    """Exploration phase state."""
    tables_found: list[str]       # Confirmed table names
    schema_search_count: int      # search_schemas call count
    last_search_empty: bool       # Most recent search_schemas returned empty
    steps: int                    # Steps taken in explore phase


class SQLState(TypedDict, total=False):
    """SQL generation & execution phase state."""
    generated_sql: str | None     # Current SQL candidate
    status: str | None            # completed | validation_failed | execution_failed
    errors: list[str]             # Accumulated error messages
    retry_count: int              # submit_sql failure retry count
    total_calls: int              # ALL submit_sql calls (exploration + final)
    last_result: dict | None      # Last execution result (columns/rows/row_count)


class CBState(TypedDict, total=False):
    """Circuit breaker signals — written by tools/agents, read by routing."""
    # Per-phase trackers
    explore: ExploreState
    sql: SQLState

    # Global
    total_steps: int              # Global step counter (all phases)
    empty_response_count: int     # Consecutive empty responses
    last_tool_name: str | None    # Last tool called
    last_tool_args: str | None    # Last tool args (normalized)
    same_tool_count: int          # Consecutive same-tool+same-args count
    current_phase: str            # explore | sql | answer

    # Degradation reason (set when CB triggers)
    cb_reason: str | None         # total_steps_exceeded | search_exhausted |
                                  # explore_max_steps | sql_max_retries |
                                  # duplicate_sql | empty_response | normal


class AgentState(TypedDict, total=False):
    """Top-level Agent state — v3.3 three-phase ReAct."""

    messages: Annotated[list, add_messages]
    cb: CBState                   # Circuit breaker state
    final_response: str | None
    db_connection_id: str | None
