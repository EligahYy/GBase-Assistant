"""Standard tool metadata and protocol."""

from __future__ import annotations

from dataclasses import dataclass


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
