"""Standard Tool interface and registry for the multi-agent system."""
from app.agents.tools.base import AgentTool, ToolParameter, ToolRegistry, get_tool_registry

__all__ = ["AgentTool", "ToolParameter", "ToolRegistry", "get_tool_registry", "register_all_tools"]


def register_all_tools(db_id: str = "") -> None:
    """Register all tools with the global registry. Called at graph build time."""
    from app.agents.tools.schema_tools import SearchSchemasTool, GetTableProfileTool, FindJoinPathTool
    from app.agents.tools.glossary_tool import QueryGlossaryTool
    from app.agents.tools.error_code_tool import LookupErrorCodeTool
    from app.agents.tools.status_tool import GetDatabaseStatusTool
    from app.agents.tools.sql_tools import ValidateSQLTool, ExecuteSQLTool
    from app.agents.tools.knowledge_tools import SearchKnowledgeTool

    registry = get_tool_registry()

    # SQL Agent tools
    registry.register(SearchSchemasTool(db_id=db_id), agent_types=["sql", "semantic_mapper"])
    registry.register(GetTableProfileTool(db_id=db_id), agent_types=["sql", "semantic_mapper"])
    registry.register(FindJoinPathTool(db_id=db_id), agent_types=["sql", "semantic_mapper"])
    registry.register(QueryGlossaryTool(), agent_types=["sql", "semantic_mapper"])
    registry.register(LookupErrorCodeTool(), agent_types=["sql", "knowledge", "semantic_mapper"])
    registry.register(ValidateSQLTool(), agent_types=["sql"])
    registry.register(ExecuteSQLTool(db_connection_id=db_id), agent_types=["sql"])

    # Knowledge Agent tools
    registry.register(SearchKnowledgeTool(), agent_types=["knowledge"])

    # Supervisor tools
    registry.register(GetDatabaseStatusTool(db_connection_id=db_id), agent_types=["supervisor", "semantic_mapper"])
