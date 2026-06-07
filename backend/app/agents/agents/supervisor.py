"""Supervisor Agent — pure router. Delegates all user requests to specialists.

The Supervisor is NOT an answer producer. It has exactly 3 tools:
- delegate_to_sql_specialist
- delegate_to_knowledge_specialist
- delegate_to_general

It must ALWAYS call one of these tools. It never produces user-visible text.
"""

from __future__ import annotations

from typing import Any

from app.agents.agents.prompts import SUPERVISOR_SYSTEM


def get_supervisor_tools(db_connection_id: str = "") -> list[Any]:
    """Get the Supervisor agent's tool set — only delegation tools."""
    from app.agents.tools.delegate_tools import (
        DelegateToSQLAgent,
        DelegateToKnowledgeAgent,
        DelegateToGeneralAgent,
    )

    return [
        DelegateToSQLAgent(),
        DelegateToKnowledgeAgent(),
        DelegateToGeneralAgent(),
    ]


def get_supervisor_prompt() -> str:
    """Get the Supervisor system prompt."""
    return SUPERVISOR_SYSTEM
