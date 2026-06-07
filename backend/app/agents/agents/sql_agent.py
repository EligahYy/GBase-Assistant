"""SQL Agent — ReAct agent for end-to-end NL2SQL."""

from __future__ import annotations

from typing import Any

from app.agents.agents.prompts import SQL_AGENT_SYSTEM


def get_sql_agent_tools(db_id: str = "") -> list[Any]:
    """Get tools used by the SQL specialist to ground and propose SQL."""
    from app.agents.tools.error_code_tool import LookupErrorCodeTool
    from app.agents.tools.glossary_tool import QueryGlossaryTool
    from app.agents.tools.schema_tools import FindJoinPathTool, GetTableProfileTool, SearchSchemasTool
    from app.agents.tools.sql_tools import SubmitSQLTool

    return [
        SearchSchemasTool(db_id=db_id),
        GetTableProfileTool(db_id=db_id),
        FindJoinPathTool(db_id=db_id),
        QueryGlossaryTool(),
        LookupErrorCodeTool(),
        SubmitSQLTool(),
    ]


def get_sql_agent_prompt() -> str:
    """Get the SQL Agent system prompt."""
    return SQL_AGENT_SYSTEM
