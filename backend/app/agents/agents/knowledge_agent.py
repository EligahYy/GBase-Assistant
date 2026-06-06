"""Knowledge Agent — ReAct agent for RAG-based technical Q&A."""

from __future__ import annotations

from typing import Any

from app.agents.agents.prompts import KNOWLEDGE_AGENT_SYSTEM


def get_knowledge_agent_tools() -> list[Any]:
    """Get the Knowledge Agent's tool set (2 tools)."""
    from app.agents.tools.knowledge_tools import SearchKnowledgeTool
    from app.agents.tools.error_code_tool import LookupErrorCodeTool

    return [
        SearchKnowledgeTool(),
        LookupErrorCodeTool(),
    ]


def get_knowledge_agent_prompt() -> str:
    """Get the Knowledge Agent system prompt."""
    return KNOWLEDGE_AGENT_SYSTEM
