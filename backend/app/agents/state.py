"""AgentState — LangGraph 共享状态定义。v3 ReAct Multi-Agent。

使用 TypedDict 定义，兼容 LangGraph StateGraph 的 state schema。
所有字段 total=False，Agent 只读写自己的 namespace。
"""

from typing import Annotated, TypedDict

from langgraph.graph.message import add_messages


class ReActState(TypedDict, total=False):
    """State for a single ReAct agent's internal loop.

    Used by the custom build_react_agent() factory. Each agent gets its own
    ReActState instance scoped to its subgraph.
    """

    messages: Annotated[list, add_messages]
    step_index: int  # Current step number in the ReAct loop
    finished: bool  # True when agent is done (final answer or error)
    agent_name: str  # Name of this agent (for event emission)
    max_iterations: int  # Hard limit on tool-calling iterations


class SupervisorState(TypedDict, total=False):
    """Supervisor-specific state."""

    delegated_agent: str | None
    delegation_history: list[dict]
    needs_clarification: str | None


class SQLAgentState(TypedDict, total=False):
    """SQL Agent-specific state."""

    generated_sql: str | None
    query_result: dict | None
    execution_error: str | None
    chart_config: dict | None


class KnowledgeAgentState(TypedDict, total=False):
    """Knowledge Agent-specific state."""

    knowledge_sources: list[str]


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
    conversation_id: str
    db_connection_id: str | None
    model: str
    history: list[dict]


# Backward-compatible aliases
V3AgentState = AgentState
AgentStateType = AgentState
