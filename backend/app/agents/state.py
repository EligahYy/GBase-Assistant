"""v3.4 Agent state — minimal, messages-first."""

from typing import Annotated

from langgraph.graph.message import add_messages


class AgentState(dict):
    """Typed state for the v3.4 Semantic NL2SQL Graph.

    Core fields:
    - messages: conversation history (add_messages reducer)
    - db_connection_id: target database
    - resolved_question: resolved question after multi-turn merge
    - semantic_context: SemanticContext dataclass
    - query_ir: Query IR dict
    - sql_candidate: current SQL being verified
    - sql_history: list of previous SQL attempts
    - validation_report: result from semantic validator
    - query_result: execution result from SubmitSQLTool
    - final_response: final answer text

    No CBState, no ExploreState, no SQLState. Messages IS the state.
    """

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.setdefault("messages", [])
        self.setdefault("sql_history", [])

    @property
    def messages(self) -> list:
        return self.get("messages", [])
