"""Orchestrator Agent — 意图分类与路由决策。

Phase 1 使用基于关键词的简易意图分类。Phase 3 将升级为 LLM-based 分类。
"""

from __future__ import annotations

import logging

from app.agents.state import AgentStateType

logger = logging.getLogger(__name__)

# ── 关键词分类规则 ──
_SQL_KEYWORDS = (
    "查询", "统计", "列出", "分析", "计算", "汇总",
    "SELECT", "FROM", "WHERE", "GROUP BY", "ORDER BY",
    "select", "from", "where",
)
_QA_KEYWORDS = (
    "支持", "怎么", "如何", "什么", "为什么", "错误",
    "参数", "配置", "版本", "语法",
)


def classify_intent_v2(user_message: str) -> str:
    """基于关键词的意图分类。返回 "sql" | "qa" | "general"。

    Phase 1 使用关键词规则，Phase 3 升级为 LLM-based。
    """
    for kw in _SQL_KEYWORDS:
        if kw in user_message:
            return "sql"
    for kw in _QA_KEYWORDS:
        if kw in user_message:
            return "qa"
    return "general"


def route_after_intent(state: AgentStateType) -> str:
    """根据 intent 路由到对应 Specialist。

    Orchestrator ReAct 循环的 Act 步骤。Phase 1 中 Specialist 节点为 stub，
    Phase 3 接入真实 Agent。
    """
    intent = state.get("intent") or "general"
    routing_map = {
        "sql": "semantic_mapper",
        "qa": "knowledge_specialist",
        "general": "general_specialist",
        "clarify": "response_formatter",
    }
    target = routing_map.get(intent, "general_specialist")
    logger.info("Orchestrator: intent=%s -> %s", intent, target)
    return target


def supervisor_check_node(state: AgentStateType) -> dict:
    """Supervisor: validate Semantic Mapper output, gate by confidence, route accordingly."""
    grounding = state.get("grounding") or {}
    confidence = grounding.get("confidence", 0)
    tables = grounding.get("tables", [])
    columns = grounding.get("columns", {})

    # Schema validation
    db_id = state.get("db_connection_id")
    validation = {"valid": True, "errors": [], "warnings": []}
    if db_id and tables:
        from app.agents.schema_graph import get_schema_graph
        graph = get_schema_graph(db_id)
        if graph._built:
            validation = graph.validate_mapping(tables, columns)

    if not validation["valid"]:
        logger.warning("Supervisor: schema validation failed: %s", validation["errors"])
        return {
            "needs_clarification": f"部分表/列不存在: {'; '.join(validation['errors'][:2])}",
        }

    if confidence < 0.5:
        business_terms = state.get("business_terms") or {}
        unresolved = grounding.get("unresolved_terms", [])
        clarification = "无法确认以下术语的映射关系"
        if unresolved:
            clarification += f": {', '.join(unresolved)}"
        clarification += "，请确认后重试。"
        return {"needs_clarification": clarification}

    return {}
