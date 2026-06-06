"""SQL Agent — ReAct agent for end-to-end NL2SQL."""

from __future__ import annotations

from typing import Any

from app.agents.agents.prompts import SQL_AGENT_SYSTEM


def get_sql_agent_tools(db_id: str = "", db_connection_id: str = "") -> list[Any]:
    """Get the SQL Agent's tool set (7 tools)."""
    from app.agents.tools.schema_tools import SearchSchemasTool, GetTableProfileTool, FindJoinPathTool
    from app.agents.tools.glossary_tool import QueryGlossaryTool
    from app.agents.tools.error_code_tool import LookupErrorCodeTool
    from app.agents.tools.sql_tools import ValidateSQLTool, ExecuteSQLTool

    return [
        SearchSchemasTool(db_id=db_id),
        GetTableProfileTool(db_id=db_id),
        FindJoinPathTool(db_id=db_id),
        QueryGlossaryTool(),
        ValidateSQLTool(),
        ExecuteSQLTool(db_connection_id=db_connection_id),
        LookupErrorCodeTool(),
    ]


def get_sql_agent_prompt() -> str:
    """Get the SQL Agent system prompt."""
    return SQL_AGENT_SYSTEM
