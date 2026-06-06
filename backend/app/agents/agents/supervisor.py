"""Supervisor Agent — ReAct agent that routes user requests to specialists."""

from __future__ import annotations

from typing import Any

from app.agents.agents.prompts import SUPERVISOR_SYSTEM


def get_supervisor_tools(db_connection_id: str = "") -> list[Any]:
    """Get the Supervisor agent's tool set (5 tools)."""
    from app.agents.tools.delegate_tools import (
        DelegateToSQLAgent,
        DelegateToKnowledgeAgent,
        RespondGeneralTool,
        AskUserClarificationTool,
    )
    from app.agents.tools.status_tool import GetDatabaseStatusTool

    return [
        DelegateToSQLAgent(),
        DelegateToKnowledgeAgent(),
        GetDatabaseStatusTool(db_connection_id=db_connection_id),
        RespondGeneralTool(),
        AskUserClarificationTool(),
    ]


def get_supervisor_prompt() -> str:
    """Get the Supervisor system prompt."""
    return SUPERVISOR_SYSTEM
