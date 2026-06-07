"""General Specialist prompt."""

from __future__ import annotations

from app.agents.agents.prompts import GENERAL_AGENT_SYSTEM


def get_general_agent_prompt() -> str:
    """Get the General Agent system prompt."""
    return GENERAL_AGENT_SYSTEM
