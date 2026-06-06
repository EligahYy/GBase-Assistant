"""Schema search tool implementations — SearchSchemasTool, GetTableProfileTool, FindJoinPathTool.

Converted from closure-style tool factories in semantic_mapper.py to standard AgentTool classes.
"""

from __future__ import annotations

from typing import Any

# Module-level imports for testability — allows patch() on the module.
# These are safe under TESTING=1 since they don't trigger Qdrant/Embedding init.
from app.agents.schema_graph import _graph_instances, get_schema_graph
from app.agents.tools.base import ToolParameter
from app.database import async_session_factory
from app.dependencies import get_schema_retriever


class SearchSchemasTool:
    """Tool: search for database tables relevant to a natural language query.

    Uses schema retriever (vector or fallback) to find top-k matching tables.
    """

    def __init__(self, db_id: str) -> None:
        self._db_id = db_id

    @property
    def name(self) -> str:
        return "search_schemas"

    @property
    def description(self) -> str:
        return (
            "Search for database tables relevant to a natural language query. "
            "Returns top-k tables with DDL, matching the user's business semantics."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="Natural language query describing what tables are needed",
            ),
        ]

    async def execute(self, query: str = "", **kwargs: Any) -> Any:
        """Execute schema search via retriever.

        Returns list[TableSchema] on success.
        """
        q = query or kwargs.get("query", "")
        async with async_session_factory() as session:
            retriever = get_schema_retriever(session)
            schemas = await retriever.retrieve(q, self._db_id)
        return schemas

    def format_result(self, result: Any) -> dict:
        """Format schema search results for display.

        Args:
            result: list[TableSchema] from execute().

        Returns:
            {"summary": str, "detail": list[dict]|None, "truncated": bool}
        """
        if not result:
            return {
                "summary": "未找到相关表。",
                "detail": None,
                "truncated": False,
            }

        table_count = len(result)
        table_names = [s.table_name for s in result]
        summary = f"检索到 {table_count} 个相关表: {', '.join(table_names[:5])}"

        # Truncate detail to 5 tables
        truncated = table_count > 5
        detail_schemas = result[:5] if truncated else result
        detail = [
            {
                "table_name": s.table_name,
                "description": s.description or "",
                "ddl_preview": (s.ddl[:200] + "..." if len(s.ddl) > 200 else s.ddl) if s.ddl else "",
            }
            for s in detail_schemas
        ]

        return {
            "summary": summary,
            "detail": detail,
            "truncated": truncated,
        }

    def to_openai_schema(self) -> dict:
        """Return OpenAI function-calling schema."""
        props = {}
        required = []
        for p in self.parameters:
            props[p.name] = p.to_json_schema()
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }


class GetTableProfileTool:
    """Tool: get complete column information for a specific table."""

    def __init__(self, db_id: str) -> None:
        self._db_id = db_id

    @property
    def name(self) -> str:
        return "get_table_profile"

    @property
    def description(self) -> str:
        return (
            "Get complete column information for a table: column names, data types, "
            "COMMENT labels, enum values, semantic roles, and relationships to other tables."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="table_name",
                type="string",
                description="The name of the table to inspect",
            ),
        ]

    async def execute(self, table_name: str = "", **kwargs: Any) -> str:
        """Get table profile from schema graph.

        Returns a formatted string with column details.
        """
        tname = table_name or kwargs.get("table_name", "")
        graph = get_schema_graph(self._db_id)
        if not graph._built:
            try:
                loaded = type(graph).load(self._db_id)
                if loaded:
                    _graph_instances[self._db_id] = loaded
                    graph = loaded
            except AttributeError:
                pass

        if tname not in graph.tables:
            # Check _built again in case load changed it
            if not getattr(graph, "_built", False) and not getattr(graph, "tables", None):
                return f"Table '{tname}' not found in schema (schema graph not built)."
            avail = ", ".join(list(graph.tables.keys())[:20])
            return f"Table '{tname}' not found in schema. Available tables: {avail}"

        table = graph.tables[tname]
        lines = [f"Table: {table.name}"]
        if table.label:
            lines.append(f"Label: {table.label}")
        if table.distribution:
            lines.append(f"Distribution: {table.distribution}")
        lines.append("\nColumns:")
        for col in table.columns:
            info = f"  - {col.name} | {col.data_type} | role={col.role}"
            if col.label:
                info += f" | label={col.label}"
            if col.comment:
                info += f" | comment={col.comment}"
            if col.enum_values:
                ev = ", ".join(f"{k}={v}" for k, v in col.enum_values.items())
                info += f" | enum={ev}"
            lines.append(info)
        if table.relationships:
            lines.append(f"\nRelationships ({len(table.relationships)}):")
            for rel in table.relationships:
                lines.append(f"  {rel['type']}: {rel['via']}")
        return "\n".join(lines)

    def format_result(self, result: Any) -> dict:
        """Wrap the string result for display.

        Args:
            result: str from execute().

        Returns:
            {"summary": str, "detail": dict|None, "truncated": bool}
        """
        # Extract table name from the first line if available
        summary = "未找到表信息。"
        if isinstance(result, str) and result.startswith("Table:"):
            first_line = result.split("\n")[0]
            summary = first_line
        elif isinstance(result, str):
            summary = result

        return {
            "summary": summary,
            "detail": {"raw": result} if isinstance(result, str) else None,
            "truncated": False,
        }

    def to_openai_schema(self) -> dict:
        """Return OpenAI function-calling schema."""
        props = {}
        required = []
        for p in self.parameters:
            props[p.name] = p.to_json_schema()
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }


class FindJoinPathTool:
    """Tool: find the JOIN path between two tables in the schema."""

    def __init__(self, db_id: str) -> None:
        self._db_id = db_id

    @property
    def name(self) -> str:
        return "find_join_path"

    @property
    def description(self) -> str:
        return (
            "Find the JOIN path between two tables. "
            "Returns foreign-key-based JOIN conditions when a path exists."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="table_a",
                type="string",
                description="The first table name",
            ),
            ToolParameter(
                name="table_b",
                type="string",
                description="The second table name",
            ),
        ]

    async def execute(self, table_a: str = "", table_b: str = "", **kwargs: Any) -> str:
        """Find JOIN path between two tables.

        Returns a formatted string describing the path.
        """
        ta = table_a or kwargs.get("table_a", "")
        tb = table_b or kwargs.get("table_b", "")
        graph = get_schema_graph(self._db_id)
        if not graph._built:
            loaded = type(graph).load(self._db_id)
            if loaded:
                _graph_instances[self._db_id] = loaded
                graph = loaded

        path = graph.find_join_path(ta, tb)
        if not path:
            return f"No JOIN path found between {ta} and {tb}."

        lines = [f"JOIN path ({len(path)} steps):"]
        for i, rel in enumerate(path):
            lines.append(f"  {i+1}. {rel['via']} (confidence: {rel['confidence']})")
        return "\n".join(lines)

    def format_result(self, result: Any) -> dict:
        """Wrap the string result for display.

        Args:
            result: str from execute().

        Returns:
            {"summary": str, "detail": dict|None, "truncated": bool}
        """
        summary = str(result) if isinstance(result, str) else "无法找到 JOIN 路径。"
        return {
            "summary": summary,
            "detail": {"raw": result} if isinstance(result, str) else None,
            "truncated": False,
        }

    def to_openai_schema(self) -> dict:
        """Return OpenAI function-calling schema."""
        props = {}
        required = []
        for p in self.parameters:
            props[p.name] = p.to_json_schema()
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }
