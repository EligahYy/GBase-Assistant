"""Standard Tool interface — Protocol + Registry for all Agent tools."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol, runtime_checkable


@dataclass
class ToolParameter:
    """A single parameter definition for a tool."""

    name: str
    type: str  # "string" | "integer" | "boolean" | "array" | "object"
    description: str
    required: bool = True
    enum: list[str] | None = None

    def to_json_schema(self) -> dict:
        """Convert to JSON Schema property definition."""
        schema: dict = {"type": self.type, "description": self.description}
        if self.enum:
            schema["enum"] = self.enum
        return schema


@runtime_checkable
class AgentTool(Protocol):
    """Standard Tool interface. All Agent tools MUST implement this Protocol.

    Each tool has:
    - Metadata: name, description, parameters (for LLM function-calling schema)
    - Execution: execute(**kwargs) — async, does the actual work
    - Formatting: format_result(result) — truncates/formats for frontend display
    - Schema export: to_openai_schema() — for LLM function-calling
    """

    @property
    def name(self) -> str: ...

    @property
    def description(self) -> str: ...

    @property
    def parameters(self) -> list[ToolParameter]: ...

    async def execute(self, **kwargs: Any) -> Any:
        """Execute the tool with keyword arguments. Must be async."""
        ...

    def format_result(self, result: Any) -> dict:
        """Format the execution result for frontend display.

        Returns a dict with:
            summary: str — one-line summary for collapsed view
            detail: dict | None — full data for expanded view
            truncated: bool — whether detail was truncated
        """
        ...

    def to_openai_schema(self) -> dict:
        """Convert to OpenAI/AG-UI function-calling schema.

        Returns:
            {"type": "function", "function": {"name": ..., "description": ..., "parameters": ...}}
        """
        ...


class ToolRegistry:
    """Global tool registry. Agents query it to get their tool set.

    Usage:
        registry = get_tool_registry()
        registry.register(SearchSchemasTool(), agent_types=["sql"])
        tools = registry.list_for_agent("sql")
    """

    def __init__(self):
        self._tools: dict[str, AgentTool] = {}
        self._agent_tool_map: dict[str, set[str]] = {}  # agent_type → {tool_name, ...}

    def register(self, tool: AgentTool, agent_types: list[str] | None = None) -> None:
        """Register a tool, optionally assigning it to specific agent types."""
        self._tools[tool.name] = tool
        if agent_types:
            for agent_type in agent_types:
                self._agent_tool_map.setdefault(agent_type, set()).add(tool.name)

    def get(self, name: str) -> AgentTool | None:
        """Get a tool by name."""
        return self._tools.get(name)

    def list_for_agent(self, agent_type: str) -> list[AgentTool]:
        """Get all tools registered for a specific agent type."""
        names = self._agent_tool_map.get(agent_type, [])
        return [self._tools[n] for n in names if n in self._tools]

    def to_openai_tools(self, agent_type: str) -> list[dict]:
        """Get OpenAI-format tool schemas for an agent type."""
        return [t.to_openai_schema() for t in self.list_for_agent(agent_type)]

    def clear(self) -> None:
        """Clear all registrations (for testing)."""
        self._tools.clear()
        self._agent_tool_map.clear()


# Global singleton
_registry: ToolRegistry | None = None


def get_tool_registry() -> ToolRegistry:
    """Get the global ToolRegistry singleton."""
    global _registry
    if _registry is None:
        _registry = ToolRegistry()
    return _registry
