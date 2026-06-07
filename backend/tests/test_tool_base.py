"""Tests for shared Agent tool metadata."""

from app.agents.tools.base import ToolParameter


def test_required_tool_parameter_schema():
    parameter = ToolParameter(name="query", type="string", description="Search query")

    assert parameter.required is True
    assert parameter.to_json_schema() == {"type": "string", "description": "Search query"}


def test_optional_enum_tool_parameter_schema():
    parameter = ToolParameter(
        name="sort",
        type="string",
        description="Sort order",
        required=False,
        enum=["asc", "desc"],
    )

    assert parameter.required is False
    assert parameter.to_json_schema()["enum"] == ["asc", "desc"]
