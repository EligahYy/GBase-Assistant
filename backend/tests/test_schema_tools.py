"""Tests for schema_tools — SearchSchemasTool, GetTableProfileTool, FindJoinPathTool."""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.tools.schema_tools import (
    FindJoinPathTool,
    GetTableProfileTool,
    SearchSchemasTool,
)
from app.protocols import TableSchema


class TestSearchSchemasTool:
    @pytest.fixture
    def tool(self):
        return SearchSchemasTool(db_id="test-db-123")

    def test_name_and_description(self, tool):
        assert tool.name == "search_schemas"
        assert "search" in tool.description.lower()

    def test_parameters(self, tool):
        params = tool.parameters
        assert len(params) == 1
        assert params[0].name == "query"
        assert params[0].type == "string"

    def test_to_openai_schema(self, tool):
        schema = tool.to_openai_schema()
        assert schema["type"] == "function"
        assert schema["function"]["name"] == "search_schemas"
        assert "query" in str(schema["function"]["parameters"])

    @pytest.mark.asyncio
    async def test_execute_returns_tables(self, tool):
        mock_schema = TableSchema(
            table_name="orders",
            ddl="CREATE TABLE orders (id INT, amount DECIMAL(10,2))",
            description="Order table",
        )
        with patch("app.agents.tools.schema_tools.async_session_factory") as mock_factory, \
             patch("app.agents.tools.schema_tools.get_schema_retriever") as mock_retriever:
            mock_retriever.return_value.retrieve = AsyncMock(return_value=[mock_schema])
            mock_session = AsyncMock()
            mock_factory.return_value.__aenter__ = AsyncMock(return_value=mock_session)
            mock_factory.return_value.__aexit__ = AsyncMock(return_value=None)

            result = await tool.execute(query="sales")
            assert len(result) == 1
            assert result[0].table_name == "orders"

    def test_format_result(self, tool):
        schemas = [
            TableSchema(table_name="orders", ddl="CREATE TABLE orders ...", description="desc1"),
            TableSchema(table_name="products", ddl="CREATE TABLE products ...", description="desc2"),
        ]
        formatted = tool.format_result(schemas)
        assert "orders" in formatted["summary"]
        assert "products" in formatted["summary"]
        assert formatted["truncated"] is False

    def test_format_result_truncated(self, tool):
        schemas = [TableSchema(table_name=f"t{i}", ddl="...", description="") for i in range(10)]
        formatted = tool.format_result(schemas)
        assert formatted["truncated"] is True
        assert len(formatted["detail"]) == 5


class TestGetTableProfileTool:
    @pytest.fixture
    def tool(self):
        return GetTableProfileTool(db_id="test-db-123")

    def test_name(self, tool):
        assert tool.name == "get_table_profile"

    def test_parameters(self, tool):
        params = tool.parameters
        assert params[0].name == "table_name"
        assert params[0].type == "string"

    @pytest.mark.asyncio
    async def test_execute_table_not_in_schema(self, tool):
        with patch("app.agents.tools.schema_tools.get_schema_graph") as mock_graph:
            mock_graph.return_value._built = False
            mock_graph.return_value.tables = {}
            result = await tool.execute(table_name="missing")
            assert "not found" in result.lower()


class TestFindJoinPathTool:
    @pytest.fixture
    def tool(self):
        return FindJoinPathTool(db_id="test-db-123")

    def test_name(self, tool):
        assert tool.name == "find_join_path"

    def test_parameters(self, tool):
        params = tool.parameters
        names = [p.name for p in params]
        assert "table_a" in names
        assert "table_b" in names

    @pytest.mark.asyncio
    async def test_execute_no_path(self, tool):
        with patch("app.agents.tools.schema_tools.get_schema_graph") as mock_graph:
            mock_graph.return_value._built = True
            mock_graph.return_value.find_join_path = MagicMock(return_value=None)
            result = await tool.execute(table_a="a", table_b="b")
            assert "No JOIN path" in result
