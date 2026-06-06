"""Tests for app.agents.tools.base — ToolParameter, AgentTool Protocol, ToolRegistry."""
import pytest

from app.agents.tools.base import ToolParameter


class TestToolParameter:
    def test_create_required_param(self):
        p = ToolParameter(name="query", type="string", description="Search query")
        assert p.name == "query"
        assert p.type == "string"
        assert p.required is True
        assert p.enum is None

    def test_create_optional_param_with_enum(self):
        p = ToolParameter(
            name="sort",
            type="string",
            description="Sort order",
            required=False,
            enum=["asc", "desc"],
        )
        assert p.required is False
        assert p.enum == ["asc", "desc"]

    def test_to_json_schema_string(self):
        p = ToolParameter(name="name", type="string", description="Table name")
        schema = p.to_json_schema()
        assert schema == {"type": "string", "description": "Table name"}

    def test_to_json_schema_with_enum(self):
        p = ToolParameter(
            name="order",
            type="string",
            description="Sort order",
            required=False,
            enum=["asc", "desc"],
        )
        schema = p.to_json_schema()
        assert schema["enum"] == ["asc", "desc"]

    def test_to_json_schema_integer(self):
        p = ToolParameter(name="limit", type="integer", description="Max rows")
        schema = p.to_json_schema()
        assert schema["type"] == "integer"


class TestToolRegistry:
    @pytest.fixture
    def registry(self):
        # Fresh instance for test isolation (not the singleton)
        from app.agents.tools.base import ToolRegistry as TR

        return TR()

    def test_register_and_get(self, registry):
        from app.agents.tools.base import ToolParameter

        class FakeTool:
            name = "test_tool"
            description = "A test tool"
            parameters = [ToolParameter(name="x", type="string", description="Input")]

            async def execute(self, **kwargs):
                return {"result": kwargs.get("x")}

            def format_result(self, result):
                return {"summary": str(result)}

            def to_openai_schema(self):
                return {
                    "type": "function",
                    "function": {
                        "name": self.name,
                        "description": self.description,
                        "parameters": {
                            "type": "object",
                            "properties": {"x": {"type": "string", "description": "Input"}},
                            "required": ["x"],
                        },
                    },
                }

        tool = FakeTool()
        registry.register(tool, agent_types=["sql"])
        assert registry.get("test_tool") is tool
        assert len(registry.list_for_agent("sql")) == 1

    def test_list_for_agent_filters(self, registry):
        class ToolA:
            name = "tool_a"
            description = "A"
            parameters = []

            async def execute(self, **kw):
                return {}

            def format_result(self, r):
                return {"summary": ""}

            def to_openai_schema(self):
                return {}

        class ToolB:
            name = "tool_b"
            description = "B"
            parameters = []

            async def execute(self, **kw):
                return {}

            def format_result(self, r):
                return {"summary": ""}

            def to_openai_schema(self):
                return {}

        registry.register(ToolA(), agent_types=["sql"])
        registry.register(ToolB(), agent_types=["knowledge"])

        sql_tools = registry.list_for_agent("sql")
        assert len(sql_tools) == 1
        assert sql_tools[0].name == "tool_a"

        knowledge_tools = registry.list_for_agent("knowledge")
        assert len(knowledge_tools) == 1
        assert knowledge_tools[0].name == "tool_b"

    def test_to_openai_tools(self, registry):
        from app.agents.tools.base import ToolParameter

        class FakeTool:
            name = "fake"
            description = "desc"
            parameters = [ToolParameter(name="q", type="string", description="Query")]

            async def execute(self, **kw):
                return {}

            def format_result(self, r):
                return {"summary": ""}

            def to_openai_schema(self):
                return {
                    "type": "function",
                    "function": {
                        "name": "fake",
                        "description": "desc",
                        "parameters": {
                            "type": "object",
                            "properties": {"q": {"type": "string", "description": "Query"}},
                            "required": ["q"],
                        },
                    },
                }

        registry.register(FakeTool(), agent_types=["sql"])
        schemas = registry.to_openai_tools("sql")
        assert len(schemas) == 1
        assert schemas[0]["function"]["name"] == "fake"

    def test_get_missing_tool_returns_none(self, registry):
        assert registry.get("nonexistent") is None

    def test_clear_removes_all_registrations(self, registry):
        class FakeTool:
            name = "t1"
            description = "desc"
            parameters = []

            async def execute(self, **kw):
                return {}

            def format_result(self, r):
                return {"summary": ""}

            def to_openai_schema(self):
                return {}

        registry.register(FakeTool(), agent_types=["sql"])
        assert registry.get("t1") is not None
        assert len(registry.list_for_agent("sql")) == 1

        registry.clear()
        assert registry.get("t1") is None
        assert len(registry.list_for_agent("sql")) == 0

    def test_duplicate_agent_type_does_not_duplicate_tool(self, registry):
        class FakeTool:
            name = "dup_tool"
            description = "desc"
            parameters = []

            async def execute(self, **kw):
                return {}

            def format_result(self, r):
                return {"summary": ""}

            def to_openai_schema(self):
                return {}

        registry.register(FakeTool(), agent_types=["sql", "sql"])
        tools = registry.list_for_agent("sql")
        assert len(tools) == 1


class TestGetToolRegistry:
    def test_singleton_returns_same_instance(self):
        from app.agents.tools.base import get_tool_registry

        reg1 = get_tool_registry()
        reg2 = get_tool_registry()
        assert reg1 is reg2

    def test_singleton_is_tool_registry_instance(self):
        from app.agents.tools.base import get_tool_registry, ToolRegistry

        reg = get_tool_registry()
        assert isinstance(reg, ToolRegistry)
