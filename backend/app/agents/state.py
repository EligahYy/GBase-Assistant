"""AgentState — LangGraph 共享状态定义。

使用 TypedDict 定义，兼容 LangGraph StateGraph 的 state schema。
所有字段 total=False，Agent 只读写自己的字段。
"""

from typing import Annotated, Literal, TypedDict

from langgraph.graph.message import add_messages


class AgentState(TypedDict, total=False):
    """多 Agent 共享状态。

    字段所有权：
    - Orchestrator: intent
    - Schema Grounding: grounding, needs_clarification
    - SQL Specialist: generated_sql, sql_retry_count
    - SQL Verifier: validation_errors, validation_passed
    - SQL Executor: query_result, execution_error
    - Knowledge Specialist: retrieved_docs, knowledge_sources
    - Output: final_response, confidence_score
    """

    # ── 消息历史（跨 Agent 共享，只增不减） ──
    messages: Annotated[list, add_messages]

    # ── Orchestrator 专属 ──
    intent: Literal["sql", "qa", "general", "clarify"]

    # ── Schema Grounding 专属（Phase 3 使用） ──
    grounding: dict | None
    needs_clarification: str | None

    # ── SQL Specialist 专属（Phase 3 使用） ──
    generated_sql: str | None
    sql_retry_count: int

    # ── SQL Verifier 专属（Phase 3 使用） ──
    validation_errors: list[str]
    validation_passed: bool

    # ── SQL Executor 专属（Phase 3 使用） ──
    query_result: dict | None
    execution_error: str | None

    # ── Knowledge Specialist 专属（Phase 3 使用） ──
    retrieved_docs: list[dict]
    knowledge_sources: list[str]

    # ── Semantic Mapper 专属 ──
    business_terms: dict | None
    chart_config: dict | None
    retrieved_schemas: list | None

    # ── 输出 ──
    final_response: str | None
    confidence_score: int

    # ── 元数据 ──
    conversation_id: str
    db_connection_id: str | None
    model: str


# 类型别名供其他模块使用
AgentStateType = AgentState
