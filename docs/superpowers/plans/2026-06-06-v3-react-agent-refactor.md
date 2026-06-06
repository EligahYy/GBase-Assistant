# V3 Multi-Agent ReAct + Tool Architecture Refactor — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Refactor GBase 8a Assistant from a static 10-node DAG pipeline to a 2-SubGraph ReAct Agent architecture with standardized Tool interface and full streaming observability (THINKING + TOOL_CALL + STEP lifecycle).

**Architecture:** 3 Phase incremental migration. Phase 1 standardizes Tool interface + AG-UI events without behavior change. Phase 2 converges 10 nodes into 2 ReAct SubGraphs (Supervisor → SQL/Knowledge), runs dual-track with v2. Phase 3 removes deprecated code.

**Tech Stack:** Python 3.12, LangGraph StateGraph, LangChain BaseChatModel, FastAPI SSE, Vue 3 + Naive UI + TypeScript, SQLite

---

## File Structure Map

```
backend/app/agents/
├── state.py                    # MODIFY: add ReActState + sub-states
├── tools/                      # CREATE: new directory
│   ├── __init__.py             # CREATE: ToolRegistry singleton
│   ├── base.py                 # CREATE: AgentTool Protocol, ToolParameter, ToolRegistry
│   ├── schema_tools.py         # CREATE: SearchSchemasTool, GetTableProfileTool, FindJoinPathTool
│   ├── glossary_tool.py        # CREATE: QueryGlossaryTool
│   ├── sql_tools.py            # CREATE: ValidateSQLTool, ExecuteSQLTool
│   ├── knowledge_tools.py      # CREATE: SearchKnowledgeTool
│   ├── error_code_tool.py      # CREATE: LookupErrorCodeTool
│   ├── status_tool.py          # CREATE: GetDatabaseStatusTool
│   └── delegate_tools.py       # CREATE: DelegateToSQLAgent, DelegateToKnowledgeAgent
├── agents/                     # CREATE: new directory
│   ├── __init__.py             # CREATE
│   ├── react_agent.py          # CREATE: build_react_agent(), _react_agent_node(), _tool_execution_node()
│   ├── supervisor.py           # CREATE: SupervisorAgent prompts + tool list
│   ├── sql_agent.py            # CREATE: SQLAgent prompts + tool list
│   ├── knowledge_agent.py      # CREATE: KnowledgeAgent prompts + tool list
│   └── general_agent.py        # CREATE: GeneralAgent (respond_general tool)
├── prompts.py                  # MODIFY: add v3 agent system prompts
├── graph.py                    # MODIFY: build_v3_graph() + dual-track run
├── semantic_mapper.py          # Phase 3: DELETE
└── orchestrator.py             # Phase 3: DELETE

backend/app/gateway/
└── ag_ui_encoder.py            # MODIFY: add THINKING_*/STEP_* events + methods

frontend/src/
├── composables/useSSE.ts       # MODIFY: add new event type union members
├── stores/chat.ts              # MODIFY: add StreamingState + tool call tracking
└── components/chat/
    └── MessageBubble.vue        # MODIFY: render THINKING fold + TOOL_CALL cards + agent steps
```

---

## Phase 1: Tool Standardization + Streaming Events (No Behavior Change)

### Task 1: Create Tool Base Classes

**Files:**
- Create: `backend/app/agents/tools/__init__.py`
- Create: `backend/app/agents/tools/base.py`

**Purpose:** Define `ToolParameter`, `AgentTool` Protocol, and `ToolRegistry` — the foundation all tools will implement.

- [ ] **Step 1: Write ToolParameter dataclass tests**

Create `backend/tests/test_tool_base.py`:

```python
"""Tests for app.agents.tools.base — ToolParameter, AgentTool Protocol, ToolRegistry."""
import pytest
from app.agents.tools.base import ToolParameter, ToolRegistry


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
        # Reset singleton for test isolation
        from app.agents.tools.base import ToolRegistry as TR
        reg = TR()
        reg._tools.clear()
        reg._agent_tool_map.clear()
        return reg

    def test_register_and_get(self, registry):
        from app.agents.tools.base import AgentTool, ToolParameter

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
        from app.agents.tools.base import ToolParameter

        class ToolA:
            name = "tool_a"; description = "A"
            parameters = []
            async def execute(self, **kw): return {}
            def format_result(self, r): return {"summary": ""}
            def to_openai_schema(self): return {}

        class ToolB:
            name = "tool_b"; description = "B"
            parameters = []
            async def execute(self, **kw): return {}
            def format_result(self, r): return {"summary": ""}
            def to_openai_schema(self): return {}

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
            name = "fake"; description = "desc"
            parameters = [ToolParameter(name="q", type="string", description="Query")]
            async def execute(self, **kw): return {}
            def format_result(self, r): return {"summary": ""}
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && TESTING=1 python -m pytest tests/test_tool_base.py -v
```
Expected: FAIL — module `app.agents.tools.base` does not exist

- [ ] **Step 3: Create `backend/app/agents/tools/__init__.py`**

```python
"""Standard Tool interface and registry for the multi-agent system."""
from app.agents.tools.base import AgentTool, ToolParameter, ToolRegistry

__all__ = ["AgentTool", "ToolParameter", "ToolRegistry"]
```

- [ ] **Step 4: Create `backend/app/agents/tools/base.py`**

```python
"""Standard Tool interface — Protocol + Registry for all Agent tools."""

from __future__ import annotations

from dataclasses import dataclass, field
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
        self._agent_tool_map: dict[str, list[str]] = {}  # agent_type → [tool_name, ...]

    def register(self, tool: AgentTool, agent_types: list[str] | None = None) -> None:
        """Register a tool, optionally assigning it to specific agent types."""
        self._tools[tool.name] = tool
        if agent_types:
            for agent_type in agent_types:
                self._agent_tool_map.setdefault(agent_type, []).append(tool.name)

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
```

- [ ] **Step 5: Run tests to verify they pass**

```bash
cd backend && TESTING=1 python -m pytest tests/test_tool_base.py -v
```
Expected: PASS (7 tests)

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/tools/__init__.py backend/app/agents/tools/base.py backend/tests/test_tool_base.py
git commit -m "feat: add AgentTool Protocol + ToolRegistry base classes"
```

---

### Task 2: Implement Schema Search Tools

**Files:**
- Create: `backend/app/agents/tools/schema_tools.py`
- Create: `backend/tests/test_schema_tools.py`

**Purpose:** Convert `_make_search_schema_semantic_tool()`, `_make_get_table_profile_tool()`, `_make_find_join_path_tool()` closures into standard `AgentTool` classes.

- [ ] **Step 1: Write tests**

Create `backend/tests/test_schema_tools.py`:

```python
"""Tests for schema_tools — SearchSchemasTool, GetTableProfileTool, FindJoinPathTool."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from app.agents.tools.base import ToolParameter
from app.agents.tools.schema_tools import (
    SearchSchemasTool,
    GetTableProfileTool,
    FindJoinPathTool,
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
            mock_factory.return_value.__aenter__ = AsyncMock()
            mock_factory.return_value.__aexit__ = AsyncMock()

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
    async def test_execute_table_not_built(self, tool):
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
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && TESTING=1 python -m pytest tests/test_schema_tools.py -v
```
Expected: FAIL — module `app.agents.tools.schema_tools` does not exist

- [ ] **Step 3: Create `backend/app/agents/tools/schema_tools.py`**

```python
"""Schema-related tools: search, profile, join path."""

from __future__ import annotations

from typing import Any

from app.agents.tools.base import AgentTool, ToolParameter
from app.protocols import TableSchema


class SearchSchemasTool:
    """Semantic search for database tables relevant to a natural language query."""

    def __init__(self, db_id: str):
        self._db_id = db_id

    @property
    def name(self) -> str:
        return "search_schemas"

    @property
    def description(self) -> str:
        return (
            "Search for database tables relevant to a natural language query. "
            "Returns top-k tables with their DDL and descriptions. "
            "Use this FIRST when exploring an unfamiliar schema."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="Natural language description of the data you need (e.g. 'sales by product')",
            ),
        ]

    async def execute(self, query: str) -> list[TableSchema]:
        from app.dependencies import get_schema_retriever
        from app.database import async_session_factory

        async with async_session_factory() as session:
            retriever = get_schema_retriever(session)
            return await retriever.retrieve(query, self._db_id)

    def format_result(self, result: list[TableSchema]) -> dict:
        tables = result
        summary = (
            f"找到 {len(tables)} 张表: {', '.join(t.table_name for t in tables[:5])}"
            if tables
            else "未找到相关表"
        )
        detail = [
            {"table": t.table_name, "description": t.description, "ddl_preview": t.ddl[:100] if t.ddl else ""}
            for t in tables[:5]
        ]
        return {
            "summary": summary,
            "detail": detail,
            "truncated": len(tables) > 5,
        }

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Natural language description of the data needed"},
                    },
                    "required": ["query"],
                },
            },
        }


class GetTableProfileTool:
    """Get complete column info for a specific table."""

    def __init__(self, db_id: str):
        self._db_id = db_id

    @property
    def name(self) -> str:
        return "get_table_profile"

    @property
    def description(self) -> str:
        return (
            "Get complete column information for a table: column names, types, roles "
            "(PRIMARY_KEY, MEASURE, TIME_DIMENSION, ENUM, FOREIGN_KEY), labels, "
            "comments, enum values, and relationships to other tables. "
            "Use this to understand table structure BEFORE writing SQL."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="table_name",
                type="string",
                description="Exact table name (e.g. 'orders')",
            ),
        ]

    async def execute(self, table_name: str) -> str:
        from app.agents.schema_graph import get_schema_graph, SchemaGraph

        graph = get_schema_graph(self._db_id)
        if not graph._built:
            loaded = SchemaGraph.load(self._db_id)
            if loaded:
                from app.agents.schema_graph import _graph_instances
                _graph_instances[self._db_id] = loaded
                graph = loaded

        if table_name not in graph.tables:
            avail = ", ".join(list(graph.tables.keys())[:20])
            return f"Table '{table_name}' not found in schema. Available tables: {avail}"

        table = graph.tables[table_name]
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

    def format_result(self, result: str) -> dict:
        # Parse column count from the text result
        col_count = result.count("  - ")
        table_line = result.split("\n")[0] if result else ""
        return {
            "summary": f"{table_line}: {col_count} 列",
            "detail": {"text": result},
            "truncated": False,
        }

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "table_name": {
                            "type": "string",
                            "description": "Exact table name to profile",
                        },
                    },
                    "required": ["table_name"],
                },
            },
        }


class FindJoinPathTool:
    """Find JOIN path between two tables."""

    def __init__(self, db_id: str):
        self._db_id = db_id

    @property
    def name(self) -> str:
        return "find_join_path"

    @property
    def description(self) -> str:
        return (
            "Find the JOIN path between two tables. Returns the FK-based JOIN conditions "
            "needed to connect them in a SQL query. Use when you need columns from "
            "multiple tables that don't have a direct relationship."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(name="table_a", type="string", description="First table name"),
            ToolParameter(name="table_b", type="string", description="Second table name"),
        ]

    async def execute(self, table_a: str, table_b: str) -> str:
        from app.agents.schema_graph import get_schema_graph, SchemaGraph

        graph = get_schema_graph(self._db_id)
        if not graph._built:
            loaded = SchemaGraph.load(self._db_id)
            if loaded:
                from app.agents.schema_graph import _graph_instances
                _graph_instances[self._db_id] = loaded
                graph = loaded

        path = graph.find_join_path(table_a, table_b)
        if not path:
            return f"No JOIN path found between {table_a} and {table_b}."
        lines = [f"JOIN path ({len(path)} steps):"]
        for i, rel in enumerate(path):
            lines.append(f"  {i+1}. {rel['via']} (confidence: {rel['confidence']})")
        return "\n".join(lines)

    def format_result(self, result: str) -> dict:
        has_path = "JOIN path" in result
        return {
            "summary": result.split("\n")[0] if result else "No result",
            "detail": {"text": result},
            "truncated": False,
        }

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "table_a": {"type": "string", "description": "First table name"},
                        "table_b": {"type": "string", "description": "Second table name"},
                    },
                    "required": ["table_a", "table_b"],
                },
            },
        }
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && TESTING=1 python -m pytest tests/test_schema_tools.py -v
```
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/tools/schema_tools.py backend/tests/test_schema_tools.py
git commit -m "feat: implement schema tools (SearchSchemas, GetTableProfile, FindJoinPath)"
```

---

### Task 3: Implement Remaining Phase 1 Tools

**Files:**
- Create: `backend/app/agents/tools/glossary_tool.py`
- Create: `backend/app/agents/tools/error_code_tool.py`
- Create: `backend/app/agents/tools/status_tool.py`
- Create: `backend/app/agents/tools/sql_tools.py`
- Create: `backend/app/agents/tools/knowledge_tools.py`

**Purpose:** Convert the remaining 3 closure tools + add 3 new tools (ValidateSQL, ExecuteSQL, SearchKnowledge) as standard Tool classes.

- [ ] **Step 1: Create `backend/app/agents/tools/glossary_tool.py`**

```python
"""QueryGlossaryTool — business glossary term lookup."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.agents.tools.base import AgentTool, ToolParameter


class QueryGlossaryTool:
    """Search business glossary for term → (table, column) mappings."""

    @property
    def name(self) -> str:
        return "query_glossary"

    @property
    def description(self) -> str:
        return (
            "Search the business glossary for a term. Returns matching (table, column) "
            "mappings. The glossary maps business terms like '销售额' to schema objects. "
            "Use this FIRST before schema search for known business terms."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="term",
                type="string",
                description="Business term to look up (e.g. '销售额', '客户数')",
            ),
        ]

    def _load_glossary(self) -> dict:
        filepath = Path(__file__).parent.parent.parent.parent / "config" / "glossary.yaml"
        if not filepath.exists():
            return {}
        with open(filepath, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        return data.get("terms", {}) or {}

    async def execute(self, term: str) -> str:
        glossary = self._load_glossary()
        if not glossary:
            return "术语表为空，请使用 search_schemas 检索数据库 Schema。"

        # Exact match
        if term in glossary:
            info = glossary[term]
            if isinstance(info, dict):
                return f"术语 '{term}' → 表 {info.get('table', '?')}.{info.get('column', '?')}"

        # Synonym match
        for key, info in glossary.items():
            if not isinstance(info, dict):
                continue
            synonyms = info.get("synonyms", []) or []
            if term in synonyms:
                return (
                    f"术语 '{term}' (同义词 of '{key}') → "
                    f"表 {info.get('table', '?')}.{info.get('column', '?')}"
                )

        return f"未找到匹配的业务术语 '{term}'。请尝试 search_schemas。"

    def format_result(self, result: str) -> dict:
        return {"summary": result, "detail": None, "truncated": False}

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "term": {"type": "string", "description": "Business term to look up"},
                    },
                    "required": ["term"],
                },
            },
        }
```

- [ ] **Step 2: Create `backend/app/agents/tools/error_code_tool.py`**

```python
"""LookupErrorCodeTool — GBase 8a error code semantic search."""

from __future__ import annotations

import logging

from app.agents.tools.base import AgentTool, ToolParameter

logger = logging.getLogger(__name__)


class LookupErrorCodeTool:
    """Semantic search for GBase 8a error codes."""

    @property
    def name(self) -> str:
        return "lookup_error"

    @property
    def description(self) -> str:
        return (
            "Search GBase 8a error codes by semantic similarity. "
            "Returns error code, description, and solution. "
            "Use when a SQL execution returns an error code."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="Error code or error description (e.g. '1064', 'syntax error')",
            ),
        ]

    async def execute(self, query: str, top_k: int = 5) -> str:
        try:
            from app.config import get_settings
            from app.vector.client import get_qdrant_manager
            from app.vector.embedder import get_embedder

            embedder = get_embedder()
            qdrant = get_qdrant_manager().client
            collection = (
                get_settings()
                .models_config.get("collections", {})
                .get("error_codes", "error_codes")
            )

            embeddings = await embedder.embed([query])
            results = await qdrant.query_points(
                collection_name=collection,
                query=embeddings[0],
                limit=top_k,
            )
            results = results.points if results else []

            if not results:
                return "未找到匹配的错误码。建议查阅 GBase 8a 官方手册。"

            lines = [f"错误码检索结果 (top-{top_k}):"]
            for i, r in enumerate(results):
                payload = r.payload or {}
                score = float(r.score) if r.score is not None else 0.0
                code = payload.get("code", "?")
                desc = payload.get("description", "")
                solution = payload.get("solution", "")
                line = f"\n{i+1}. [{code}] (相似度: {score:.2f})\n   描述: {desc}"
                if solution:
                    line += f"\n   解决方案: {solution[:200]}"
                lines.append(line)
            return "\n".join(lines)
        except Exception as e:
            logger.warning("Error code search failed: %s", e)
            return f"错误码检索失败: {e}"

    def format_result(self, result: str) -> dict:
        return {"summary": result.split("\n")[0] if result else "", "detail": {"text": result}, "truncated": False}

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Error code or description to search"},
                    },
                    "required": ["query"],
                },
            },
        }
```

- [ ] **Step 3: Create `backend/app/agents/tools/status_tool.py`**

```python
"""GetDatabaseStatusTool — database runtime status quick path."""

from __future__ import annotations

import asyncio
import json
import logging

from sqlalchemy import select

from app.agents.tools.base import AgentTool, ToolParameter
from app.models.connection import DbConnection

logger = logging.getLogger(__name__)


class GetDatabaseStatusTool:
    """Query database runtime status via system tables. Fast path, no SQL generation."""

    def __init__(self, db_connection_id: str = ""):
        self._db_connection_id = db_connection_id

    @property
    def name(self) -> str:
        return "get_database_status"

    @property
    def description(self) -> str:
        return (
            "Query database runtime status: connection count, active queries, uptime, "
            "table summary. Uses predefined system table queries — NO SQL generation needed. "
            "Use for monitoring questions like '数据库状态', '有多少连接'."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return []  # No parameters — queries all status metrics

    async def execute(self) -> str:
        if not self._db_connection_id:
            return json.dumps({"error": "未选择数据库连接"}, ensure_ascii=False)

        from app.database import async_session_factory
        from app.db_connectors.connector_factory import get_connector
        from app.api.connections import _to_connection_config
        from app.sql.sandbox import SQLSandbox

        async with async_session_factory() as session:
            result = await session.execute(
                select(DbConnection).where(DbConnection.id == self._db_connection_id)
            )
            conn = result.scalar_one_or_none()
        if not conn:
            return json.dumps({"error": "连接不存在"}, ensure_ascii=False)

        connector = get_connector(conn.driver_type)
        config = _to_connection_config(conn)

        queries = {
            "连接数": "SELECT COUNT(*) AS cnt FROM information_schema.PROCESSLIST",
            "活跃SQL": (
                "SELECT id, user, host, db, time, state, LEFT(info,200) AS info "
                "FROM information_schema.PROCESSLIST WHERE time > 0"
            ),
            "运行时间": "SELECT DATEDIFF(NOW(), MIN(create_time)) AS running_days FROM information_schema.TABLES",
            "表概况": (
                "SELECT TABLE_NAME, TABLE_ROWS, ROUND(DATA_LENGTH/1024/1024,2) AS size_mb "
                "FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() "
                "ORDER BY DATA_LENGTH DESC LIMIT 20"
            ),
        }

        async def _run_one(label: str, sql: str) -> tuple[str, dict]:
            try:
                sandbox = SQLSandbox()
                qr = await sandbox.execute_readonly(connector, config, sql, max_rows=100, timeout_seconds=10)
                return label, {"columns": qr.columns, "rows": qr.rows, "row_count": qr.row_count}
            except Exception as e:
                return label, {"error": str(e)}

        results = {}
        tasks = [_run_one(label, sql) for label, sql in queries.items()]
        gathered = await asyncio.gather(*tasks)
        for label, data in gathered:
            results[label] = data

        return json.dumps(results, ensure_ascii=False, default=str)

    def format_result(self, result: str) -> dict:
        try:
            data = json.loads(result)
            parts = []
            for label, info in data.items():
                if isinstance(info, dict) and "error" in info:
                    parts.append(f"{label}: 错误")
                elif isinstance(info, dict):
                    parts.append(f"{label}: {info.get('row_count', 0)} 行")
            return {"summary": ", ".join(parts), "detail": data, "truncated": False}
        except (json.JSONDecodeError, TypeError):
            return {"summary": result[:100], "detail": {"text": result}, "truncated": len(result) > 100}

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": {}, "required": []},
            },
        }
```

- [ ] **Step 4: Create `backend/app/agents/tools/sql_tools.py`**

```python
"""SQL execution tools: ValidateSQL, ExecuteSQL."""

from __future__ import annotations

import logging

from app.agents.tools.base import AgentTool, ToolParameter

logger = logging.getLogger(__name__)


class ValidateSQLTool:
    """Validate SQL syntax and schema cross-reference before execution."""

    def __init__(self, db_connection_id: str = ""):
        self._db_connection_id = db_connection_id

    @property
    def name(self) -> str:
        return "validate_sql"

    @property
    def description(self) -> str:
        return (
            "Validate SQL syntax and schema consistency. Performs three-layer validation: "
            "1) sqlglot syntax parsing, 2) GBase 8a dialect compliance check, "
            "3) Schema cross-reference (table/column existence). "
            "Always validate BEFORE executing SQL."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="sql",
                type="string",
                description="The SQL statement to validate",
            ),
        ]

    async def execute(self, sql: str) -> dict:
        from app.sql.validator import validate_sql
        from app.agents.schema_graph import get_schema_graph

        result = validate_sql(sql)
        return {
            "valid": result.is_valid,
            "errors": result.errors,
            "warnings": result.warnings,
            "corrected_sql": result.corrected_sql,
        }

    def format_result(self, result: dict) -> dict:
        if result.get("valid"):
            summary = "✅ 验证通过"
        else:
            n_errors = len(result.get("errors", []))
            summary = f"❌ {n_errors} 个错误: {'; '.join(result['errors'][:2])}"
        return {
            "summary": summary,
            "detail": result,
            "truncated": False,
        }

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "SQL statement to validate"},
                    },
                    "required": ["sql"],
                },
            },
        }


class ExecuteSQLTool:
    """Execute SQL in read-only sandbox and return results."""

    def __init__(self, db_connection_id: str = ""):
        self._db_connection_id = db_connection_id

    @property
    def name(self) -> str:
        return "execute_sql"

    @property
    def description(self) -> str:
        return (
            "Execute a read-only SQL query in the GBase 8a sandbox and return results. "
            "Only SELECT/SHOW/DESCRIBE/EXPLAIN queries are allowed. "
            "Maximum 1000 rows returned, 30-second timeout. "
            "Always validate_sql() before executing."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="sql",
                type="string",
                description="The SQL SELECT statement to execute",
            ),
        ]

    async def execute(self, sql: str, max_rows: int = 1000, timeout_seconds: int = 30) -> dict:
        from app.database import async_session_factory
        from sqlalchemy import select
        from app.models.connection import DbConnection
        from app.db_connectors.connector_factory import get_connector
        from app.api.connections import _to_connection_config
        from app.sql.sandbox import SQLSandbox, SQLSandboxError

        if not self._db_connection_id:
            return {"error": "未选择数据库连接"}

        try:
            async with async_session_factory() as session:
                result = await session.execute(
                    select(DbConnection).where(DbConnection.id == self._db_connection_id)
                )
                conn = result.scalar_one_or_none()

            if not conn or conn.driver_type == "manual":
                return {"error": "数据库连接不可用"}

            connector = get_connector(conn.driver_type)
            if not connector:
                return {"error": f"驱动 {conn.driver_type} 不可用"}

            config = _to_connection_config(conn)
            sandbox = SQLSandbox()
            query_result = await sandbox.execute_readonly(
                connector, config, sql, max_rows=max_rows, timeout_seconds=timeout_seconds,
            )

            return {
                "columns": query_result.columns,
                "rows": query_result.rows[:50],
                "row_count": query_result.row_count,
                "execution_time_ms": round(query_result.execution_time_ms, 2),
                "truncated": query_result.truncated or query_result.row_count > 50,
            }
        except SQLSandboxError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("ExecuteSQL failed: %s", e)
            return {"error": str(e)}

    def format_result(self, result: dict) -> dict:
        if "error" in result:
            return {"summary": f"❌ 执行失败: {result['error']}", "detail": result, "truncated": False}
        return {
            "summary": f"✅ {result['row_count']} 行, {result['execution_time_ms']}ms",
            "detail": result,
            "truncated": result.get("truncated", False),
        }

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "sql": {"type": "string", "description": "SQL SELECT statement to execute"},
                    },
                    "required": ["sql"],
                },
            },
        }
```

- [ ] **Step 5: Create `backend/app/agents/tools/knowledge_tools.py`**

```python
"""Knowledge retrieval tool: SearchKnowledge."""

from __future__ import annotations

import logging

from app.agents.tools.base import AgentTool, ToolParameter

logger = logging.getLogger(__name__)


class SearchKnowledgeTool:
    """Hybrid knowledge base search (Qdrant semantic + ripgrep exact)."""

    @property
    def name(self) -> str:
        return "search_knowledge"

    @property
    def description(self) -> str:
        return (
            "Search the GBase 8a knowledge base (product manuals, FAQs, technical docs) "
            "for relevant information. Uses hybrid retrieval: semantic vector search + "
            "exact keyword matching. Returns ranked document chunks with sources."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="Technical question or keywords to search (e.g. '分区表语法', '错误码 1064')",
            ),
        ]

    async def execute(self, query: str) -> str:
        from app.dependencies import get_knowledge_retriever

        try:
            retriever = get_knowledge_retriever()
            chunks = await retriever.retrieve(query)
            if not chunks:
                return "未找到相关知识。建议尝试不同的关键词，或查阅 GBase 8a 官方手册。"

            lines = ["知识检索结果:"]
            for i, chunk in enumerate(chunks[:5]):
                source = chunk.source if chunk.source else "unknown"
                content_preview = chunk.content[:200].replace("\n", " ")
                lines.append(f"\n{i+1}. [{source}] {content_preview}...")
            return "\n".join(lines)
        except Exception as e:
            logger.error("Knowledge search failed: %s", e)
            return f"知识检索失败: {e}"

    def format_result(self, result: str) -> dict:
        chunk_count = result.count("\n") - 1  # rough estimate
        return {
            "summary": f"检索到 {chunk_count} 个相关文档片段" if chunk_count > 0 else "未找到相关文档",
            "detail": {"text": result},
            "truncated": False,
        }

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "Search query for knowledge base"},
                    },
                    "required": ["query"],
                },
            },
        }
```

- [ ] **Step 6: Run all Phase 1 tool tests**

```bash
cd backend && TESTING=1 python -m pytest tests/test_tool_base.py tests/test_schema_tools.py -v
```
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add backend/app/agents/tools/glossary_tool.py backend/app/agents/tools/error_code_tool.py backend/app/agents/tools/status_tool.py backend/app/agents/tools/sql_tools.py backend/app/agents/tools/knowledge_tools.py
git commit -m "feat: implement Phase 1 tools (glossary, error_code, status, sql, knowledge)"
```

---

### Task 4: Extend AG-UI EventEncoder with THINKING + STEP Events

**Files:**
- Modify: `backend/app/gateway/ag_ui_encoder.py`
- Create: `backend/tests/test_ag_ui_events.py`

**Purpose:** Add `THINKING_START/CONTENT/END` and `STEP_STARTED/FINISHED` event types + encoder methods.

- [ ] **Step 1: Write tests**

Create `backend/tests/test_ag_ui_events.py`:

```python
"""Tests for new AG-UI event types (THINKING, STEP)."""
import json
import pytest
from app.gateway.ag_ui_encoder import EventType, EventEncoder


class TestNewEventTypes:
    def test_thinking_start(self):
        sse = EventEncoder.thinking_start()
        data = json.loads(sse.split("data: ")[1].strip())
        assert data["type"] == "THINKING_START"

    def test_thinking_delta(self):
        sse = EventEncoder.thinking_delta("我需要检索表结构...")
        data = json.loads(sse.split("data: ")[1].strip())
        assert data["type"] == "THINKING_CONTENT"
        assert data["delta"] == "我需要检索表结构..."

    def test_thinking_end(self):
        sse = EventEncoder.thinking_end()
        data = json.loads(sse.split("data: ")[1].strip())
        assert data["type"] == "THINKING_END"

    def test_step_started(self):
        sse = EventEncoder.step_started("sql_agent", step_index=0)
        data = json.loads(sse.split("data: ")[1].strip())
        assert data["type"] == "STEP_STARTED"
        assert data["agent_name"] == "sql_agent"
        assert data["step_index"] == 0

    def test_step_finished(self):
        sse = EventEncoder.step_finished("sql_agent")
        data = json.loads(sse.split("data: ")[1].strip())
        assert data["type"] == "STEP_FINISHED"
        assert data["agent_name"] == "sql_agent"

    def test_existing_tool_events_still_work(self):
        sse = EventEncoder.tool_call_start("search_schemas", {"query": "sales"})
        data = json.loads(sse.split("data: ")[1].strip())
        assert data["type"] == "TOOL_CALL_START"
        assert data["tool_name"] == "search_schemas"
        assert data["args"] == {"query": "sales"}
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd backend && TESTING=1 python -m pytest tests/test_ag_ui_events.py -v
```
Expected: FAIL — `EventEncoder.thinking_start()` not defined

- [ ] **Step 3: Modify `backend/app/gateway/ag_ui_encoder.py`**

Add new enum values:

```python
class EventType(StrEnum):
    TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
    TOOL_CALL_START = "TOOL_CALL_START"
    TOOL_CALL_RESULT = "TOOL_CALL_RESULT"
    TOOL_CALL_END = "TOOL_CALL_END"
    STATE_DELTA = "STATE_DELTA"
    RUN_STARTED = "RUN_STARTED"
    RUN_FINISHED = "RUN_FINISHED"
    RUN_ERROR = "RUN_ERROR"
    # ── 🆕 Thinking visibility ──
    THINKING_START = "THINKING_START"
    THINKING_CONTENT = "THINKING_CONTENT"
    THINKING_END = "THINKING_END"
    # ── 🆕 Step lifecycle ──
    STEP_STARTED = "STEP_STARTED"
    STEP_FINISHED = "STEP_FINISHED"
```

Add new methods to EventEncoder class:

```python
    @staticmethod
    def thinking_start() -> str:
        """Emit when an agent starts its reasoning process."""
        return EventEncoder._encode(EventType.THINKING_START)

    @staticmethod
    def thinking_delta(delta: str) -> str:
        """Emit a token of thinking/reasoning content (streamed)."""
        return EventEncoder._encode(EventType.THINKING_CONTENT, delta=delta)

    @staticmethod
    def thinking_end() -> str:
        """Emit when an agent finishes its reasoning process."""
        return EventEncoder._encode(EventType.THINKING_END)

    @staticmethod
    def step_started(agent_name: str, step_index: int = 0) -> str:
        """Emit when a new agent step begins."""
        return EventEncoder._encode(
            EventType.STEP_STARTED,
            agent_name=agent_name,
            step_index=step_index,
        )

    @staticmethod
    def step_finished(agent_name: str) -> str:
        """Emit when an agent step completes."""
        return EventEncoder._encode(
            EventType.STEP_FINISHED,
            agent_name=agent_name,
        )
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
cd backend && TESTING=1 python -m pytest tests/test_ag_ui_events.py -v
```
Expected: ALL PASS

- [ ] **Step 5: Run ALL existing tests to verify no regression**

```bash
cd backend && TESTING=1 python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: 163+ tests pass, 0 fail

- [ ] **Step 6: Commit**

```bash
git add backend/app/gateway/ag_ui_encoder.py backend/tests/test_ag_ui_events.py
git commit -m "feat: add THINKING_* and STEP_* AG-UI event types"
```

---

### Task 5: Frontend SSE Type Definitions + Chat Store

**Files:**
- Modify: `frontend/src/composables/useSSE.ts`
- Modify: `frontend/src/stores/chat.ts`

**Purpose:** Add new event type handling in the frontend without changing rendering behavior yet.

- [ ] **Step 1: Update useSSE.ts type union**

In `frontend/src/composables/useSSE.ts`, update the `SSEChunk` interface:

```typescript
export interface ToolCallStartPayload {
  name: string
  args?: Record<string, unknown>
  agent_name?: string
}

export interface ToolCallResultPayload {
  name: string
  result?: Record<string, unknown>
  error?: string
}

export interface SSEChunk {
  type:
    | 'text' | 'sql' | 'sources' | 'warning' | 'done' | 'error'
    | 'result' | 'result_error' | 'message_ids'
    | 'TEXT_MESSAGE_CONTENT' | 'STATE_DELTA' | 'chart_config'
    // 🆕 Thinking visibility
    | 'THINKING_START' | 'THINKING_CONTENT' | 'THINKING_END'
    // 🆕 Tool call lifecycle
    | 'TOOL_CALL_START' | 'TOOL_CALL_RESULT' | 'TOOL_CALL_END'
    // 🆕 Step lifecycle
    | 'STEP_STARTED' | 'STEP_FINISHED'
  content?: string
  delta?: string
  path?: string
  value?: any
  tool_name?: string
  agent_name?: string
  args?: Record<string, unknown>
  result?: Record<string, unknown>
  step_index?: number
  token_usage?: Record<string, unknown>
}
```

- [ ] **Step 2: Add tool call tracking to chat store**

In `frontend/src/stores/chat.ts`, add:

```typescript
// ── 🆕 ReAct streaming state ──

export interface ToolCallEntry {
  id: string
  name: string
  args: Record<string, unknown>
  result?: string
  error?: string
  status: 'pending' | 'running' | 'done' | 'error'
  agentName: string
}

// Add to the chat store state:
const thinkingText = ref('')
const isThinking = ref(false)
const toolCalls = ref<ToolCallEntry[]>([])
const activeAgent = ref<string | null>(null)

// Add actions:
function setThinking(active: boolean) {
  isThinking.value = active
  if (!active) thinkingText.value = ''
}

function appendThinkingToken(token: string, streamingId: string) {
  thinkingText.value += token
}

function addToolCall(tc: ToolCallEntry, streamingId: string) {
  toolCalls.value = [...toolCalls.value, tc]
}

function updateToolCallStatus(name: string, status: 'done' | 'error', result?: string, error?: string) {
  const idx = toolCalls.value.findIndex(tc => tc.name === name && tc.status === 'running')
  if (idx >= 0) {
    const updated = [...toolCalls.value]
    updated[idx] = { ...updated[idx], status, result, error }
    toolCalls.value = updated
  }
}

function setActiveAgent(name: string | null) {
  activeAgent.value = name
}

function clearToolCalls() {
  toolCalls.value = []
  thinkingText.value = ''
  isThinking.value = false
  activeAgent.value = null
}
```

- [ ] **Step 3: Verify TypeScript compilation**

```bash
cd frontend && npx vue-tsc --noEmit 2>&1 | tail -5
```
Expected: No new errors introduced (existing errors ok)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/composables/useSSE.ts frontend/src/stores/chat.ts
git commit -m "feat: add frontend types + store for THINKING/TOOL_CALL/STEP events"
```

---

### Task 6: Wire New Tools into semantic_mapper_node (No Behavior Change)

**Files:**
- Modify: `backend/app/agents/semantic_mapper.py`

**Purpose:** Replace closure factories with ToolRegistry-registered tool instances. Behavior must remain identical.

- [ ] **Step 1: Register all tools at startup**

Create a `register_all_tools()` function in `backend/app/agents/tools/__init__.py`:

```python
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
    registry.register(ValidateSQLTool(db_connection_id=db_id), agent_types=["sql"])
    registry.register(ExecuteSQLTool(db_connection_id=db_id), agent_types=["sql"])

    # Knowledge Agent tools
    registry.register(SearchKnowledgeTool(), agent_types=["knowledge"])

    # Supervisor tools
    registry.register(GetDatabaseStatusTool(db_connection_id=db_id), agent_types=["supervisor"])
```

- [ ] **Step 2: Update semantic_mapper_node to use registry**

In `backend/app/agents/semantic_mapper.py`, update `build_semantic_mapper_tools()` to return ToolRegistry tools:

```python
def build_semantic_mapper_tools(glossary: dict, db_id: str):
    """Build the 6-tool set for the Semantic Mapper Agent (backward-compatible).

    Returns tools from ToolRegistry with closure-based glossary as fallback.
    """
    from app.agents.tools import get_tool_registry, register_all_tools

    register_all_tools(db_id=db_id)
    registry = get_tool_registry()

    tools = registry.list_for_agent("semantic_mapper")

    # If registry is empty (tests without full app context), fall back to closures
    if not tools:
        tools = [
            _make_query_glossary_tool(glossary),
            _make_search_schema_semantic_tool(db_id),
            _make_get_table_profile_tool(db_id),
            _make_find_join_path_tool(db_id),
        ]
        if db_id:
            tools.append(_make_get_database_status_tool(db_id))
        tools.append(_make_query_error_code_tool())
    return tools
```

- [ ] **Step 3: Run existing semantic mapper tests**

```bash
cd backend && TESTING=1 python -m pytest tests/semantic_mapper/ -v --tb=short
```
Expected: ALL PASS

- [ ] **Step 4: Run ALL existing tests**

```bash
cd backend && TESTING=1 python -m pytest tests/ -v --tb=short 2>&1 | tail -30
```
Expected: ALL PASS (>163 tests), no regression

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/tools/__init__.py backend/app/agents/semantic_mapper.py
git commit -m "feat: wire ToolRegistry tools into semantic_mapper (backward compatible)"
```

---

## Phase 2: Agent Convergence + Custom ReAct Graph

### Task 7: Implement ReAct Agent State + Routing

**Files:**
- Modify: `backend/app/agents/state.py`

**Purpose:** Add `ReActState` TypedDict and sub-states for each agent.

- [ ] **Step 1: Add ReActState to state.py**

```python
"""AgentState — LangGraph 共享状态定义。v3: adds ReActState for custom agent loops."""

from typing import Annotated, Literal, TypedDict

from langgraph.graph.message import add_messages


# ── v2 state (backward compatible, to be removed in Phase 3) ──

class AgentState(TypedDict, total=False):
    messages: Annotated[list, add_messages]
    intent: Literal["sql", "qa", "general", "clarify"]
    grounding: dict | None
    needs_clarification: str | None
    generated_sql: str | None
    sql_retry_count: int
    validation_errors: list[str]
    validation_passed: bool
    query_result: dict | None
    execution_error: str | None
    retrieved_docs: list[dict]
    knowledge_sources: list[str]
    business_terms: dict | None
    chart_config: dict | None
    retrieved_schemas: list | None
    final_response: str | None
    confidence_score: int
    conversation_id: str
    db_connection_id: str | None
    model: str
    history: list[dict]


AgentStateType = AgentState


# ── v3 ReAct state ──

class ReActState(TypedDict, total=False):
    """State for a single ReAct agent's internal loop.

    Used by the custom build_react_agent() factory. Each agent gets its own
    ReActState instance scoped to its subgraph.
    """

    messages: Annotated[list, add_messages]
    step_index: int          # Current step number in the ReAct loop
    finished: bool           # True when agent is done (final answer or error)
    agent_name: str          # Name of this agent (for event emission)
    max_iterations: int      # Hard limit on tool-calling iterations


class SupervisorState(TypedDict, total=False):
    """Supervisor-specific state."""
    delegated_agent: str | None
    delegation_history: list[dict]
    needs_clarification: str | None


class SQLAgentState(TypedDict, total=False):
    """SQL Agent-specific state."""
    generated_sql: str | None
    query_result: dict | None
    execution_error: str | None
    chart_config: dict | None


class KnowledgeAgentState(TypedDict, total=False):
    """Knowledge Agent-specific state."""
    knowledge_sources: list[str]


# ── v3 top-level state ──

class V3AgentState(TypedDict, total=False):
    """v3 top-level state: namespace-isolated per-agent state."""
    messages: Annotated[list, add_messages]
    supervisor: SupervisorState
    sql: SQLAgentState
    knowledge: KnowledgeAgentState
    final_response: str | None
    conversation_id: str
    db_connection_id: str | None
    model: str
    history: list[dict]
```

- [ ] **Step 2: Check existing state tests still pass**

```bash
cd backend && TESTING=1 python -m pytest tests/test_agents/test_state.py -v
```
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add backend/app/agents/state.py
git commit -m "feat: add ReActState + V3AgentState with namespace isolation"
```

---

### Task 8: Implement Custom build_react_agent() Factory

**Files:**
- Create: `backend/app/agents/agents/__init__.py`
- Create: `backend/app/agents/agents/react_agent.py`

**Purpose:** Replace `langgraph.prebuilt.create_react_agent` with custom implementation that emits THINKING/TOOL_CALL/STEP events via `get_stream_writer()`.

- [ ] **Step 1: Create `backend/app/agents/agents/__init__.py`**

```python
"""v3 Agent implementations — ReAct agents with streaming observability."""
```

- [ ] **Step 2: Create `backend/app/agents/agents/react_agent.py`**

```python
"""Custom ReAct Agent factory with streaming THINKING + TOOL_CALL events.

Replaces langgraph.prebuilt.create_react_agent to gain control over:
- Thinking content streaming (THINKING_START/CONTENT/END)
- Tool call lifecycle events (TOOL_CALL_START/RESULT/END)
- Step lifecycle (STEP_STARTED/FINISHED)
- Iteration limits with graceful termination
"""

from __future__ import annotations

import json
import logging
from typing import Any

from langgraph.graph import StateGraph, START, END
from langgraph.config import get_stream_writer
from langchain_core.messages import AIMessage, BaseMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.language_models import BaseChatModel

from app.agents.state import ReActState

logger = logging.getLogger(__name__)

MAX_ITERATIONS = 15


def _emit_custom(key: str, value: Any) -> None:
    """Emit a custom event through LangGraph's stream writer."""
    try:
        writer = get_stream_writer()
        writer([{key: value}])
    except RuntimeError:
        pass  # Not in a streaming context (e.g., tests)


def _parse_llm_response(response: AIMessage) -> tuple[list[dict] | None, str | None]:
    """Extract tool calls and/or text content from an AI message.

    Returns (tool_calls_list, text_content). One or both may be None.
    """
    tool_calls = None
    text = None

    # Check for native tool_calls (when model natively supports function calling)
    if hasattr(response, "tool_calls") and response.tool_calls:
        tool_calls = []
        for tc in response.tool_calls:
            tool_calls.append({
                "id": tc.get("id", f"call_{len(tool_calls)}"),
                "name": tc["name"],
                "args": tc.get("args", {}),
            })

    # Check for text content
    if hasattr(response, "content") and response.content:
        content = response.content
        if isinstance(content, str):
            text = content.strip()

    return tool_calls, text


def _build_react_agent_node(
    model: BaseChatModel,
    tools: list[Any],
    system_prompt: str,
    agent_name: str,
):
    """Create the agent reasoning node — streams THINKING events, returns tool_calls or text."""

    async def node_fn(state: ReActState) -> dict:
        step_index = state.get("step_index", 0)

        # Emit STEP_STARTED on first iteration
        if step_index == 0:
            _emit_custom("step_started", {"agent_name": agent_name, "step_index": 0})

        # Build messages: system prompt + conversation history
        messages: list[BaseMessage] = [SystemMessage(content=system_prompt)]
        existing = state.get("messages", [])
        messages.extend(existing)

        # Build tool schemas for the LLM
        tool_schemas = []
        for t in tools:
            if hasattr(t, "to_openai_schema"):
                tool_schemas.append(t.to_openai_schema())

        # ── Stream LLM response, emitting THINKING deltas ──
        full_response: AIMessage | None = None
        thinking_buffer = ""

        try:
            # Non-streaming call with tools for reliability (streaming + tools is flaky)
            # We emit a synthetic THINKING event for observability
            if hasattr(model, "_agenerate"):
                result = await model._agenerate(messages, tools=tool_schemas)
                if result.generations and result.generations[0]:
                    full_response = result.generations[0].message
            elif hasattr(model, "ainvoke"):
                full_response = await model.ainvoke(messages, tools=tool_schemas)
            else:
                # Fallback: use LiteLLM adapter's complete method
                dict_msgs = []
                for m in messages:
                    role = "system" if isinstance(m, SystemMessage) else "user"
                    if hasattr(m, "type"):
                        role = "assistant" if m.type == "ai" else ("system" if m.type == "system" else "user")
                    dict_msgs.append({"role": role, "content": str(m.content)})
                content, _ = await model.llm_client.complete(dict_msgs, tools=tool_schemas)
                full_response = AIMessage(content=content)
        except Exception as e:
            logger.error("ReAct agent %s LLM call failed: %s", agent_name, e)
            error_msg = AIMessage(content=f"处理出错: {e}")
            _emit_custom("delta", f"\n处理出错: {e}")
            return {"messages": [error_msg], "finished": True, "step_index": step_index + 1}

        # Parse response
        tool_calls, text = _parse_llm_response(full_response)

        # Emit THINKING (synthesized from the model's reasoning — for models without native thinking)
        # For models WITH native thinking (Claude), we'd stream it. For now emit a summary.
        if text and not tool_calls:
            # Final text answer — emit as regular text (NOT thinking)
            _emit_custom("delta", text)
            return {
                "messages": [full_response],
                "finished": True,
                "step_index": step_index + 1,
            }

        if tool_calls:
            # Emit a brief thinking summary about the tool choice
            thinking_summary = f"调用 {len(tool_calls)} 个工具: {', '.join(tc['name'] for tc in tool_calls)}"
            _emit_custom("thinking_start", {})
            _emit_custom("thinking_delta", thinking_summary)
            _emit_custom("thinking_end", {})

            return {
                "messages": [full_response],
                "step_index": step_index + 1,
            }

        # No tool calls and no text — force end with generic response
        fallback = AIMessage(content="处理完成。")
        _emit_custom("delta", "处理完成。")
        return {"messages": [fallback], "finished": True, "step_index": step_index + 1}

    return node_fn


def _build_tool_execution_node(tools: list[Any], agent_name: str, tool_registry=None):
    """Create the tool execution node — emits TOOL_CALL_START/RESULT/END events."""

    async def node_fn(state: ReActState) -> dict:
        messages = state.get("messages", [])
        if not messages:
            return {"messages": []}

        last_msg = messages[-1]
        tool_calls, _ = _parse_llm_response(last_msg)

        if not tool_calls:
            return {"messages": []}

        # Build name → tool mapping
        tool_map = {t.name: t for t in tools if hasattr(t, "name")}

        tool_messages = []
        for tc in tool_calls:
            tool_name = tc["name"]
            tool_args = tc.get("args", {})

            # Emit TOOL_CALL_START
            _emit_custom("tool_call_start", {
                "name": tool_name,
                "args": tool_args,
                "agent_name": agent_name,
            })

            tool = tool_map.get(tool_name)
            if tool is None:
                error_msg = f"Tool '{tool_name}' not found"
                _emit_custom("tool_call_result", {"name": tool_name, "error": error_msg})
                _emit_custom("tool_call_end", {"name": tool_name})
                tool_messages.append(ToolMessage(content=json.dumps({"error": error_msg}), tool_call_id=tc["id"]))
                continue

            try:
                # Execute the tool
                result = await tool.execute(**tool_args)

                # Format for display
                if hasattr(tool, "format_result"):
                    formatted = tool.format_result(result)
                else:
                    formatted = {"summary": str(result)[:200], "detail": None, "truncated": False}

                # Emit TOOL_CALL_RESULT
                _emit_custom("tool_call_result", {
                    "name": tool_name,
                    "result": formatted,
                })

                # Return formatted summary to the LLM (not full detail)
                tool_messages.append(ToolMessage(
                    content=formatted.get("summary", str(result)),
                    tool_call_id=tc["id"],
                ))

            except Exception as e:
                logger.error("Tool %s execution failed: %s", tool_name, e)
                _emit_custom("tool_call_result", {"name": tool_name, "error": str(e)})
                tool_messages.append(ToolMessage(
                    content=json.dumps({"error": str(e)}),
                    tool_call_id=tc["id"],
                ))

            # Emit TOOL_CALL_END
            _emit_custom("tool_call_end", {"name": tool_name})

        return {"messages": tool_messages}

    return node_fn


def _route_after_agent(state: ReActState) -> str:
    """Route: if agent has tool calls → tools node, else → END."""
    step_index = state.get("step_index", 0)
    max_iter = state.get("max_iterations", MAX_ITERATIONS)

    if state.get("finished"):
        return "end"

    if step_index >= max_iter:
        logger.warning("ReAct agent reached max iterations (%d), forcing end", max_iter)
        return "end"

    messages = state.get("messages", [])
    if not messages:
        return "end"

    last_msg = messages[-1]
    tool_calls, _ = _parse_llm_response(last_msg)

    if tool_calls:
        return "tools"

    return "end"


def build_react_agent(
    model: BaseChatModel,
    tools: list[Any],
    system_prompt: str,
    agent_name: str,
    max_iterations: int = MAX_ITERATIONS,
) -> StateGraph:
    """Build a custom ReAct Agent subgraph with streaming observability.

    Args:
        model: LangChain-compatible chat model
        tools: List of AgentTool instances
        system_prompt: System prompt for the agent
        agent_name: Name for event emission (e.g. "sql_agent", "supervisor")
        max_iterations: Hard limit on tool-calling iterations (default 15)

    Returns:
        Compiled LangGraph StateGraph ready to use as a subgraph node
    """
    builder = StateGraph(ReActState)

    agent_node = _build_react_agent_node(model, tools, system_prompt, agent_name)
    tools_node = _build_tool_execution_node(tools, agent_name)

    builder.add_node("agent", agent_node)
    builder.add_node("tools", tools_node)

    builder.add_edge(START, "agent")
    builder.add_conditional_edges("agent", _route_after_agent, {
        "tools": "tools",
        "end": END,
    })
    builder.add_edge("tools", "agent")

    return builder.compile()
```

- [ ] **Step 2: Run existing tests to verify no import errors**

```bash
cd backend && TESTING=1 python -c "from app.agents.agents.react_agent import build_react_agent; print('OK')"
```
Expected: `OK`

- [ ] **Step 3: Commit**

```bash
git add backend/app/agents/agents/__init__.py backend/app/agents/agents/react_agent.py
git commit -m "feat: implement custom build_react_agent() with streaming events"
```

---

### Task 9: Implement Agent System Prompts

**Files:**
- Modify: `backend/app/llm/prompts.py` (or new file `backend/app/agents/prompts.py`)

**Purpose:** Add Supervisor, SQL, and Knowledge agent system prompts as defined in the spec.

- [ ] **Step 1: Create `backend/app/agents/agents/prompts.py`**

```python
"""System prompts for v3 ReAct agents."""

# ── Supervisor Agent ───────────────────────────────────────────────────────────────

SUPERVISOR_SYSTEM = """你是 GBase 8a 数据库 AI 助手的主管 Agent。你的职责是理解用户意图并委托给合适的专家 Agent。

## 决策规则

1. **数据查询、SQL 生成、数据库 schema 相关** → 调用 `delegate_to_sql_specialist`
2. **GBase 8a 技术知识、错误码、配置、语法问题** → 调用 `delegate_to_knowledge_specialist`
3. **数据库状态监控（连接数、运行时间、表概况）** → 调用 `get_database_status`（快速通道）
4. **问候、闲聊、超出 GBase 范围** → 调用 `respond_general`
5. **意图不明确** → 先回答，然后引导用户提供更多信息

## 重要原则

- 每次只委托一个 Agent，观察结果后再决定下一步
- 如果 Agent 返回失败或不确定，切换策略而非强行继续
- 保持对话连贯性，记住之前的委托历史
- 用中文回复用户

## 当前上下文

用户选择了数据库连接。你可以用 `get_database_status` 快速查看数据库状态。
如果没有选择数据库连接，SQL 查询将无法执行，请引导用户先添加连接。
"""


# ── SQL Agent ──────────────────────────────────────────────────────────────────────

SQL_AGENT_SYSTEM = """你是 GBase 8a SQL 专家 Agent。你的任务是端到端处理数据查询请求：

理解需求 → 探索 Schema → 生成 SQL → 验证 → 执行 → 返回结果

## 工作流（灵活调整，不必严格线性）

1. **探索阶段**：用 `search_schemas` 找到相关表
2. **确认阶段**：用 `get_table_profile` 查看列结构、角色、枚举值
3. **术语映射**：必要时用 `query_glossary` 查业务术语（如"销售额"）
4. **关联查找**：多表查询时用 `find_join_path` 找 JOIN 关联
5. **生成阶段**：生成 GBase 8a 兼容的 SQL
6. **验证阶段**：用 `validate_sql` 验证语法和 Schema 一致性
7. **执行阶段**：用 `execute_sql` 执行获取结果
8. **纠错阶段**：如果失败，分析错误并修正（最多 3 轮）

## GBase 8a 方言约束（必须严格遵守）

- 只支持只读查询（SELECT/SHOW/DESCRIBE/EXPLAIN）
- 不支持 UPDATE/DELETE/INSERT/DROP/ALTER/TRUNCATE/CREATE
- 不支持 WINDOW 子句的 RANGE/ROWS 帧定义
- 不支持 WITH RECURSIVE CTE
- LIMIT 语法: `LIMIT n OFFSET m` 或 `LIMIT m,n`
- 字符串连接用 `CONCAT()`，不用 `||`
- 日期运算用 `CURDATE() - INTERVAL 1 MONTH`，不用 `DATE_SUB`
- 不支持 FULL OUTER JOIN
- 使用 `GROUP_CONCAT` 而非 `STRING_AGG`

## 输出格式

完成所有工具调用后，用中文输出：
1. 生成的 SQL（用 ```sql 代码块包裹）
2. 查询结果摘要（行数、耗时）
3. 如果结果适合图表展示，说明推荐的图表类型

不要输出任何其他内容。
"""


# ── Knowledge Agent ────────────────────────────────────────────────────────────────

KNOWLEDGE_AGENT_SYSTEM = """你是 GBase 8a 知识专家 Agent。回答 GBase 8a 相关的技术问题。

## 工作流

1. **检索阶段**：用 `search_knowledge` 检索相关文档
2. **补充检索**：如果检索结果不足以回答问题，尝试用不同关键词再搜
3. **错误码查询**：遇到错误码问题，用 `lookup_error` 查询
4. **回答阶段**：基于检索结果用中文回答，注明来源
5. **诚实原则**：如果知识库没有答案，诚实说明并给出查阅官方手册的建议

## 输出要求

- 准确、简洁，直接回答问题
- 如有代码示例，用代码块格式化
- 基于知识库回答时注明来源
- 不要编造知识库中没有的信息
"""


# ── General Agent (used by Supervisor's respond_general tool) ──────────────────────

GENERAL_AGENT_SYSTEM = """你是 GBase 8a 数据库助手。你可以进行友好对话。

如果用户的问题涉及数据查询或技术问题，引导他们描述具体需求：
- 数据查询：引导用户说明要查什么数据、按什么维度统计
- 技术问题：引导用户具体说明遇到的技术点

保持友好、简洁的中文回复风格。
"""
```

- [ ] **Step 2: Commit**

```bash
git add backend/app/agents/agents/prompts.py
git commit -m "feat: add v3 agent system prompts (supervisor, sql, knowledge, general)"
```

---

### Task 10: Implement Supervisor + Delegate Tools

**Files:**
- Create: `backend/app/agents/tools/delegate_tools.py`
- Create: `backend/app/agents/agents/supervisor.py`

**Purpose:** Delegate tools that invoke sub-agents, and the Supervisor agent definition.

- [ ] **Step 1: Create `backend/app/agents/tools/delegate_tools.py`**

```python
"""Delegate tools — Supervisor tools that invoke specialist sub-agents."""

from __future__ import annotations

import json
import logging

from app.agents.tools.base import AgentTool, ToolParameter

logger = logging.getLogger(__name__)


class DelegateToSQLAgent:
    """Delegate a data query request to the SQL Agent subgraph.

    This tool is called by the Supervisor. When executed, it triggers the
    SQL Agent subgraph which handles the full NL2SQL pipeline autonomously.
    """

    @property
    def name(self) -> str:
        return "delegate_to_sql_specialist"

    @property
    def description(self) -> str:
        return (
            "Delegate a data query request to the SQL specialist agent. "
            "The SQL agent will autonomously: explore the database schema, "
            "generate GBase 8a SQL, validate it, execute it, and return results. "
            "Use for: data queries, statistics, reports, chart data, monitoring queries."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="The user's natural language query (pass the original user message)",
            ),
        ]

    async def execute(self, query: str) -> dict:
        # This tool's execute() is never called directly — it serves as a signal
        # to the graph router. The actual sub-agent invocation happens in graph.py.
        return {"status": "delegated", "query": query}

    def format_result(self, result: dict) -> dict:
        return {"summary": f"委托 SQL Agent 处理: {result.get('query', '')[:50]}...", "detail": result, "truncated": False}

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The user's natural language data query",
                        },
                    },
                    "required": ["query"],
                },
            },
        }


class DelegateToKnowledgeAgent:
    """Delegate a knowledge question to the Knowledge Agent subgraph."""

    @property
    def name(self) -> str:
        return "delegate_to_knowledge_specialist"

    @property
    def description(self) -> str:
        return (
            "Delegate a GBase 8a technical question to the Knowledge specialist agent. "
            "The Knowledge agent will search the product documentation and answer "
            "technical questions about GBase 8a features, syntax, configuration, errors. "
            "Use for: 'how to' questions, error codes, syntax reference, configuration."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="The user's technical question",
            ),
        ]

    async def execute(self, query: str) -> dict:
        return {"status": "delegated", "query": query}

    def format_result(self, result: dict) -> dict:
        return {"summary": f"委托 Knowledge Agent 处理: {result.get('query', '')[:50]}...", "detail": result, "truncated": False}

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {
                            "type": "string",
                            "description": "The user's technical question",
                        },
                    },
                    "required": ["query"],
                },
            },
        }


class RespondGeneralTool:
    """Direct text response for casual conversation. No sub-agent needed."""

    @property
    def name(self) -> str:
        return "respond_general"

    @property
    def description(self) -> str:
        return (
            "Send a direct conversational response to the user. "
            "Use for: greetings, casual chat, topics outside GBase 8a scope, "
            "or when the user needs guidance on what they can ask."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="message",
                type="string",
                description="The message to send to the user (in Chinese)",
            ),
        ]

    async def execute(self, message: str) -> str:
        return message

    def format_result(self, result: str) -> dict:
        return {"summary": result, "detail": None, "truncated": False}

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {
                            "type": "string",
                            "description": "Response message to send to user",
                        },
                    },
                    "required": ["message"],
                },
            },
        }


class AskUserClarificationTool:
    """Ask the user for clarification when intent is unclear."""

    @property
    def name(self) -> str:
        return "ask_user_clarification"

    @property
    def description(self) -> str:
        return (
            "Ask the user for clarification when their request is ambiguous. "
            "Use when: the intent is unclear, multiple interpretations are possible, "
            "or required information is missing (e.g., no database selected)."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="question",
                type="string",
                description="The clarification question to ask the user",
            ),
        ]

    async def execute(self, question: str) -> str:
        return question

    def format_result(self, result: str) -> dict:
        return {"summary": result, "detail": None, "truncated": False}

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {
                            "type": "string",
                            "description": "Clarification question to ask",
                        },
                    },
                    "required": ["question"],
                },
            },
        }
```

- [ ] **Step 2: Create `backend/app/agents/agents/supervisor.py`**

```python
"""Supervisor Agent — ReAct agent that routes user requests to specialists."""

from __future__ import annotations

from typing import Any

from app.agents.agents.prompts import SUPERVISOR_SYSTEM
from app.agents.tools.base import get_tool_registry


def get_supervisor_tools(db_connection_id: str = "") -> list[Any]:
    """Get the Supervisor agent's tool set."""
    from app.agents.tools.delegate_tools import (
        DelegateToSQLAgent,
        DelegateToKnowledgeAgent,
        RespondGeneralTool,
        AskUserClarificationTool,
    )
    from app.agents.tools.status_tool import GetDatabaseStatusTool

    return [
        DelegateToSQLAgent(),
        DelegateToKnowledgeAgent(),
        GetDatabaseStatusTool(db_connection_id=db_connection_id),
        RespondGeneralTool(),
        AskUserClarificationTool(),
    ]


def get_supervisor_prompt() -> str:
    """Get the Supervisor system prompt."""
    return SUPERVISOR_SYSTEM
```

- [ ] **Step 3: Run import check**

```bash
cd backend && TESTING=1 python -c "from app.agents.agents.supervisor import get_supervisor_tools; t = get_supervisor_tools(); print(f'{len(t)} supervisor tools loaded')"
```
Expected: `5 supervisor tools loaded`

- [ ] **Step 4: Commit**

```bash
git add backend/app/agents/tools/delegate_tools.py backend/app/agents/agents/supervisor.py
git commit -m "feat: implement supervisor tools (delegate, respond, clarify) + agent def"
```

---

### Task 11: Implement SQL + Knowledge Agent Definitions

**Files:**
- Create: `backend/app/agents/agents/sql_agent.py`
- Create: `backend/app/agents/agents/knowledge_agent.py`
- Create: `backend/app/agents/agents/general_agent.py`

**Purpose:** Define tool sets and prompts for SQL and Knowledge agents.

- [ ] **Step 1: Create `backend/app/agents/agents/sql_agent.py`**

```python
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
        ValidateSQLTool(db_connection_id=db_connection_id),
        ExecuteSQLTool(db_connection_id=db_connection_id),
        LookupErrorCodeTool(),
    ]


def get_sql_agent_prompt() -> str:
    """Get the SQL Agent system prompt."""
    return SQL_AGENT_SYSTEM
```

- [ ] **Step 2: Create `backend/app/agents/agents/knowledge_agent.py`**

```python
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
```

- [ ] **Step 3: Create `backend/app/agents/agents/general_agent.py`**

```python
"""General Agent — simple chat response (used by Supervisor's respond_general tool)."""

from __future__ import annotations

from app.agents.agents.prompts import GENERAL_AGENT_SYSTEM


def get_general_agent_prompt() -> str:
    """Get the General Agent system prompt."""
    return GENERAL_AGENT_SYSTEM
```

- [ ] **Step 4: Verify imports**

```bash
cd backend && TESTING=1 python -c "
from app.agents.agents.sql_agent import get_sql_agent_tools
from app.agents.agents.knowledge_agent import get_knowledge_agent_tools
print(f'SQL: {len(get_sql_agent_tools())} tools')
print(f'Knowledge: {len(get_knowledge_agent_tools())} tools')
"
```
Expected: `SQL: 7 tools` / `Knowledge: 2 tools`

- [ ] **Step 5: Commit**

```bash
git add backend/app/agents/agents/sql_agent.py backend/app/agents/agents/knowledge_agent.py backend/app/agents/agents/general_agent.py
git commit -m "feat: implement SQL + Knowledge agent tool sets and prompts"
```

---

### Task 12: Implement v3 Graph (Dual-Track)

**Files:**
- Modify: `backend/app/agents/graph.py`

**Purpose:** Add `build_v3_graph()` alongside existing `build_graph()`. Add dual-track `run_agent_with_ag_ui()` with feature flag.

- [ ] **Step 1: Add build_v3_graph() to graph.py**

```python
# ── v3 Graph (ReAct Agent architecture) ──

def build_v3_graph(db_connection_id: str = "") -> StateGraph:
    """Build v3 ReAct Agent graph: Supervisor → (SQL | Knowledge) SubGraphs.

    The Supervisor is a ReAct agent that dynamically delegates to specialist
    sub-agents. Each specialist is itself a ReAct agent with its own tool set.
    """
    from app.agents.state import V3AgentState
    from app.agents.agents.react_agent import build_react_agent
    from app.agents.agents.supervisor import get_supervisor_tools, get_supervisor_prompt
    from app.agents.agents.sql_agent import get_sql_agent_tools, get_sql_agent_prompt
    from app.agents.agents.knowledge_agent import get_knowledge_agent_tools, get_knowledge_agent_prompt
    from app.dependencies import get_llm_client
    from app.agents.semantic_mapper import _LiteLLMChatAdapter

    builder = StateGraph(V3AgentState)

    # ── Create chat models ──
    supervisor_llm = get_llm_client(task_type="general")  # Fast/cheap for routing
    specialist_llm = get_llm_client(task_type="sql")       # Full power for SQL

    # ── Build sub-agents ──
    supervisor_subgraph = build_react_agent(
        model=_LiteLLMChatAdapter(supervisor_llm),
        tools=get_supervisor_tools(db_connection_id),
        system_prompt=get_supervisor_prompt(),
        agent_name="supervisor",
    )

    sql_subgraph = build_react_agent(
        model=_LiteLLMChatAdapter(specialist_llm),
        tools=get_sql_agent_tools(db_id=db_connection_id, db_connection_id=db_connection_id),
        system_prompt=get_sql_agent_prompt(),
        agent_name="sql_agent",
    )

    knowledge_subgraph = build_react_agent(
        model=_LiteLLMChatAdapter(specialist_llm),
        tools=get_knowledge_agent_tools(),
        system_prompt=get_knowledge_agent_prompt(),
        agent_name="knowledge_agent",
    )

    # ── Register nodes ──
    builder.add_node("supervisor", supervisor_subgraph)
    builder.add_node("sql_agent", sql_subgraph)
    builder.add_node("knowledge_agent", knowledge_subgraph)
    builder.add_node("response_formatter", _v3_response_formatter_node)

    builder.add_edge(START, "supervisor")

    # Route based on supervisor's tool choice
    def route_supervisor(state):
        """Route supervisor's tool_call to the right sub-agent or response."""
        msgs = state.get("messages", [])
        if not msgs:
            return "response_formatter"

        last_msg = msgs[-1]
        if hasattr(last_msg, "tool_calls") and last_msg.tool_calls:
            for tc in last_msg.tool_calls:
                name = tc.get("name", "")
                if name == "delegate_to_sql_specialist":
                    return "sql_agent"
                if name == "delegate_to_knowledge_specialist":
                    return "knowledge_agent"
                if name in ("respond_general", "ask_user_clarification", "get_database_status"):
                    return "response_formatter"

        return "response_formatter"

    builder.add_conditional_edges("supervisor", route_supervisor, {
        "sql_agent": "sql_agent",
        "knowledge_agent": "knowledge_agent",
        "response_formatter": "response_formatter",
    })

    # Sub-agents return to supervisor for potential re-delegation
    builder.add_edge("sql_agent", "supervisor")
    builder.add_edge("knowledge_agent", "supervisor")
    builder.add_edge("response_formatter", END)

    return builder.compile(checkpointer=MemorySaver())


async def _v3_response_formatter_node(state) -> dict:
    """Format the final response from any agent."""
    msgs = state.get("messages", [])
    final_text = ""

    for msg in reversed(msgs):
        if hasattr(msg, "content") and msg.content:
            content = msg.content
            if isinstance(content, str):
                # Skip delegate tool call results (they're internal)
                if "delegated" not in content.lower() and "status" not in content.lower():
                    # Check if it looks like a real response (not tool metadata)
                    skip_patterns = ['{"status":', '{"error":', '{"summary":']
                    if not any(content.strip().startswith(p) for p in skip_patterns):
                        final_text = content
                        break

    if not final_text:
        final_text = "处理完成。如有其他问题，请继续提问。"

    return {"final_response": final_text}
```

- [ ] **Step 2: Add dual-track run with feature flag**

Add the following function to `graph.py` to enable A/B comparison:

```python
async def run_agent_with_ag_ui(
    user_message: str,
    conversation_id: str,
    model: str,
    db_connection_id: str | None = None,
    use_v3: bool = False,  # 🆕 feature flag
) -> AsyncIterator[str]:
    """Run LangGraph Agent with AG-UI token-level streaming SSE output.

    Args:
        use_v3: If True, use v3 ReAct architecture. Default False (v2).
    """
    if use_v3:
        async for event in _run_v3_agent(user_message, conversation_id, model, db_connection_id):
            yield event
    else:
        # Existing v2 code (unchanged)
        graph = build_graph()
        # ... existing v2 run logic ...
```

- [ ] **Step 3: Add v3 streaming function**

```python
async def _run_v3_agent(
    user_message: str,
    conversation_id: str,
    model: str,
    db_connection_id: str | None = None,
) -> AsyncIterator[str]:
    """Run v3 ReAct Agent graph with full streaming observability."""
    from app.agents.state import V3AgentState

    graph = build_v3_graph(db_connection_id=db_connection_id or "")

    # Load history
    history = []
    if conversation_id:
        try:
            from app.database import async_session_factory
            from app.models.conversation import Conversation
            from app.services.conversation_service import build_context
            from sqlalchemy import select

            async with async_session_factory() as session:
                result = await session.execute(select(Conversation).where(Conversation.id == conversation_id))
                conv = result.scalar_one_or_none()
                if conv:
                    ctx = await build_context(session, conv)
                    history = ctx.history or []
        except Exception:
            pass

    initial_state: V3AgentState = {
        "messages": [HumanMessage(content=user_message)],
        "conversation_id": conversation_id,
        "model": model,
        "db_connection_id": db_connection_id,
        "history": history,
        "supervisor": {},
        "sql": {},
        "knowledge": {},
    }

    yield EventEncoder.run_started(conversation_id)

    config = {"configurable": {"thread_id": f"v3_{conversation_id}"}}
    streamed_text = False

    try:
        async for mode, events in graph.astream(initial_state, config=config, stream_mode=["custom", "updates"]):
            if mode == "custom":
                for ev in events:
                    if isinstance(ev, dict):
                        # ── 🆕 Thinking events ──
                        if "thinking_start" in ev:
                            yield EventEncoder.thinking_start()
                        elif "thinking_delta" in ev:
                            yield EventEncoder.thinking_delta(ev["thinking_delta"])
                        elif "thinking_end" in ev:
                            yield EventEncoder.thinking_end()

                        # ── 🆕 Step events ──
                        elif "step_started" in ev:
                            info = ev["step_started"]
                            yield EventEncoder.step_started(info.get("agent_name", "unknown"), info.get("step_index", 0))

                        # ── 🆕 Tool call events ──
                        elif "tool_call_start" in ev:
                            info = ev["tool_call_start"]
                            yield EventEncoder.tool_call_start(info["name"], info.get("args"))
                        elif "tool_call_result" in ev:
                            info = ev["tool_call_result"]
                            yield EventEncoder.tool_call_result(info["name"], info.get("result", {}))
                        elif "tool_call_end" in ev:
                            yield EventEncoder.tool_call_end(ev.get("name", "unknown"))

                        # ── Text delta ──
                        elif "delta" in ev:
                            yield EventEncoder.text_delta(ev["delta"])
                            streamed_text = True

        # Get final state
        final_state = await graph.aget_state(config)
        state_values = final_state.values if final_state else {}
        response = state_values.get("final_response", "") if state_values else ""

        if response and not streamed_text:
            yield EventEncoder.text_delta(response)

        yield EventEncoder.run_finished()

    except Exception as e:
        logger.error("v3 Agent run failed: %s", e)
        yield EventEncoder.run_error(str(e))
```

- [ ] **Step 4: Verify compilation**

```bash
cd backend && TESTING=1 python -c "
from app.agents.graph import build_v3_graph
g = build_v3_graph()
print('v3 graph built:', g)
"
```
Expected: `v3 graph built: CompiledStateGraph(...)`

- [ ] **Step 5: Run all existing tests to verify no regression**

```bash
cd backend && TESTING=1 python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add backend/app/agents/graph.py
git commit -m "feat: implement v3 graph (Supervisor + SubGraphs) with dual-track feature flag"
```

---

### Task 13: Frontend MessageBubble — Render THINKING + TOOL_CALL + Agent Steps

**Files:**
- Modify: `frontend/src/components/chat/MessageBubble.vue`
- Modify: `frontend/src/stores/chat.ts`

**Purpose:** Add visual rendering for thinking fold, tool call cards, and agent step indicators.

- [ ] **Step 1: Update chat store for streaming events**

Wire the event handlers in the ChatPanel sendMessage flow to update the store. Add action handlers in `chat.ts`:

```typescript
// In chat store actions:
function handleThinkingStart(streamingId: string) {
  isThinking.value = true
  thinkingText.value = ''
}

function handleThinkingDelta(streamingId: string, delta: string) {
  thinkingText.value += delta
}

function handleThinkingEnd(streamingId: string) {
  // Keep thinking text visible, mark as complete
  isThinking.value = false
}

function handleToolCallStart(streamingId: string, toolName: string, args?: Record<string, unknown>, agentName?: string) {
  toolCalls.value = [...toolCalls.value, {
    id: `${toolName}-${Date.now()}`,
    name: toolName,
    args: args || {},
    status: 'running' as const,
    agentName: agentName || 'unknown',
  }]
}

function handleToolCallResult(streamingId: string, toolName: string, result?: any, error?: string) {
  updateToolCallStatus(toolName, error ? 'error' : 'done', result?.summary, error)
}

function handleToolCallEnd(streamingId: string, toolName: string) {
  // Tool call cycle complete — no action needed (already updated in result handler)
}

function handleStepStarted(streamingId: string, agentName: string) {
  activeAgent.value = agentName
}

function handleStepFinished(streamingId: string) {
  // Keep in context, don't clear yet
}
```

- [ ] **Step 2: Update ChatPanel.vue to route new events**

In `frontend/src/components/chat/ChatPanel.vue`, add cases to the `streamPost` callback:

```typescript
} else if (chunk.type === 'THINKING_START') {
  chatStore.handleThinkingStart(streamingId)
} else if (chunk.type === 'THINKING_CONTENT') {
  chatStore.handleThinkingDelta(streamingId, chunk.delta || '')
} else if (chunk.type === 'THINKING_END') {
  chatStore.handleThinkingEnd(streamingId)
} else if (chunk.type === 'TOOL_CALL_START') {
  chatStore.handleToolCallStart(streamingId, chunk.tool_name || 'unknown', chunk.args as Record<string, unknown> | undefined, chunk.agent_name)
} else if (chunk.type === 'TOOL_CALL_RESULT') {
  chatStore.handleToolCallResult(streamingId, chunk.tool_name || 'unknown', chunk.result, undefined)
} else if (chunk.type === 'TOOL_CALL_END') {
  chatStore.handleToolCallEnd(streamingId, chunk.tool_name || 'unknown')
} else if (chunk.type === 'STEP_STARTED') {
  chatStore.handleStepStarted(streamingId, chunk.agent_name || 'unknown')
} else if (chunk.type === 'STEP_FINISHED') {
  chatStore.handleStepFinished(streamingId)
```

- [ ] **Step 3: Create ThinkingSection.vue component**

Create `frontend/src/components/chat/ThinkingSection.vue`:

```vue
<script setup lang="ts">
import { ref } from 'vue'

const props = defineProps<{
  thinking: string
  isThinking: boolean
}>()

const expanded = ref(true)  // Auto-expand while thinking
</script>

<template>
  <div v-if="thinking" class="thinking-section">
    <button class="thinking-toggle" @click="expanded = !expanded">
      <span class="thinking-icon">{{ isThinking ? '🔍' : '💭' }}</span>
      <span class="thinking-label">{{ isThinking ? '思考中...' : '思考过程' }}</span>
      <span class="thinking-chevron">{{ expanded ? '▾' : '▸' }}</span>
    </button>
    <div v-if="expanded" class="thinking-content">
      {{ thinking }}
      <span v-if="isThinking" class="thinking-cursor">|</span>
    </div>
  </div>
</template>

<style scoped>
.thinking-section {
  margin-bottom: 8px;
  font-size: 13px;
}
.thinking-toggle {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 2px 0;
  background: none;
  border: none;
  color: var(--text-3);
  cursor: pointer;
  font-family: var(--font-sans);
  font-size: 12px;
}
.thinking-toggle:hover { color: var(--text-2); }
.thinking-icon { font-size: 12px; }
.thinking-label { font-weight: 500; }
.thinking-chevron { font-size: 10px; margin-left: 2px; }
.thinking-content {
  color: var(--text-3);
  font-style: italic;
  padding: 4px 0 4px 24px;
  line-height: 1.5;
  white-space: pre-wrap;
  word-break: break-word;
}
.thinking-cursor {
  animation: blink 1s step-end infinite;
  font-style: normal;
}
@keyframes blink {
  50% { opacity: 0; }
}
</style>
```

- [ ] **Step 4: Create ToolCallCard.vue component**

Create `frontend/src/components/chat/ToolCallCard.vue`:

```vue
<script setup lang="ts">
import { ref } from 'vue'
import type { ToolCallEntry } from '@/stores/chat'

const props = defineProps<{
  toolCall: ToolCallEntry
}>()

const expanded = ref(false)

const statusIcon = {
  running: '🔄',
  done: '✅',
  error: '❌',
  pending: '⏳',
}

const statusText = {
  running: '执行中',
  done: '完成',
  error: '失败',
  pending: '等待',
}
</script>

<template>
  <div class="tool-call-card" :class="`status-${toolCall.status}`">
    <button class="tool-call-header" @click="expanded = !expanded">
      <span class="tool-status">{{ statusIcon[toolCall.status] }}</span>
      <span class="tool-name">{{ toolCall.name }}</span>
      <span class="tool-status-text">{{ statusText[toolCall.status] }}</span>
      <span class="tool-chevron">{{ expanded ? '▾' : '▸' }}</span>
    </button>
    <div v-if="expanded" class="tool-call-detail">
      <div v-if="Object.keys(toolCall.args).length" class="tool-args">
        <span class="detail-label">参数:</span>
        <code>{{ JSON.stringify(toolCall.args, null, 2) }}</code>
      </div>
      <div v-if="toolCall.result" class="tool-result">
        <span class="detail-label">结果:</span>
        <span>{{ toolCall.result }}</span>
      </div>
      <div v-if="toolCall.error" class="tool-error">
        <span class="detail-label">错误:</span>
        <span>{{ toolCall.error }}</span>
      </div>
    </div>
  </div>
</template>

<style scoped>
.tool-call-card {
  margin: 4px 0 4px 24px;
  font-size: 12px;
  border: 1px solid var(--seam-1);
  border-radius: var(--radius-sm);
  overflow: hidden;
}
.tool-call-header {
  display: flex;
  align-items: center;
  gap: 6px;
  padding: 4px 8px;
  width: 100%;
  background: var(--bg-panel);
  border: none;
  cursor: pointer;
  font-family: var(--font-sans);
  font-size: 12px;
  color: var(--text-2);
}
.tool-call-header:hover { background: var(--bg-hover); }
.tool-name { font-family: var(--font-mono); color: var(--text-1); font-weight: 500; }
.tool-status-text { color: var(--text-4); font-size: 11px; margin-left: auto; }
.tool-chevron { font-size: 10px; color: var(--text-4); }
.tool-call-detail { padding: 4px 8px 8px; background: var(--bg-deep); }
.tool-args code, .tool-result, .tool-error {
  font-family: var(--font-mono);
  font-size: 11px;
  white-space: pre-wrap;
  word-break: break-word;
  display: block;
  margin-top: 2px;
  color: var(--text-2);
}
.tool-error { color: var(--error); }
.detail-label { color: var(--text-4); font-size: 10px; text-transform: uppercase; }
.status-error { border-color: var(--error); }
.status-done { border-color: var(--success); }
</style>
```

- [ ] **Step 5: Add agent step indicator to MessageBubble**

In `frontend/src/components/chat/MessageBubble.vue`, add to the AI message rendering:

```vue
<!-- Agent step indicator — show when agent steps are active -->
<div v-if="message.activeAgent" class="agent-step-indicator">
  <span class="agent-icon">
    {{ message.activeAgent === 'sql_agent' ? '🤖' : message.activeAgent === 'knowledge_agent' ? '📚' : '🧠' }}
  </span>
  <span class="agent-label">
    {{ message.activeAgent === 'sql_agent' ? 'SQL Agent' : message.activeAgent === 'knowledge_agent' ? 'Knowledge Agent' : message.activeAgent }}
  </span>
  <span class="agent-status">处理中...</span>
</div>
```

- [ ] **Step 6: Wire everything together in MessageBubble**

Update `MessageBubble.vue` to include the new components above the message content:

```vue
<template>
  <div class="message-bubble" :class="[`role-${message.role}`, { streaming: message.isStreaming }]">
    <!-- Agent Step Indicator -->
    <div v-if="message.activeAgent" class="agent-step-indicator">
      ...
    </div>

    <!-- Thinking Section -->
    <ThinkingSection
      :thinking="message.thinking || ''"
      :is-thinking="message.isThinking || false"
    />

    <!-- Tool Call Cards -->
    <ToolCallCard
      v-for="tc in message.toolCalls"
      :key="tc.id"
      :tool-call="tc"
    />

    <!-- Actual message content -->
    <div class="message-content" v-html="renderedContent" />

    <!-- SQL block -->
    <div v-if="message.sql" class="sql-block">...</div>

    <!-- Query result table -->
    <div v-if="message.queryResult" class="result-block">...</div>

    <!-- Sources -->
    <div v-if="message.sources" class="sources-block">...</div>
  </div>
</template>
```

- [ ] **Step 7: Extend Message type in store**

Update the ChatMessage interface in `chat.ts`:

```typescript
export interface ChatMessage {
  id: string
  role: 'user' | 'assistant'
  content: string
  isStreaming?: boolean
  // 🆕 ReAct streaming state
  thinking?: string
  isThinking?: boolean
  toolCalls?: ToolCallEntry[]
  activeAgent?: string | null
  // Existing
  sql?: string
  queryResult?: any
  chartConfig?: any
  sources?: string
  timestamp: number
}
```

- [ ] **Step 8: Verify TypeScript compilation**

```bash
cd frontend && npx vue-tsc --noEmit 2>&1 | tail -10
```
Expected: No new errors

- [ ] **Step 9: Commit**

```bash
git add frontend/src/components/chat/ThinkingSection.vue frontend/src/components/chat/ToolCallCard.vue frontend/src/components/chat/MessageBubble.vue frontend/src/components/chat/ChatPanel.vue frontend/src/stores/chat.ts frontend/src/composables/useSSE.ts
git commit -m "feat: add THINKING + TOOL_CALL + agent step rendering in chat UI"
```

---

## Phase 3: Cleanup

### Task 14: Remove Deprecated Code + Finalize State

**Files:**
- Modify: `backend/app/agents/state.py` — remove v2 state
- Modify: `backend/app/agents/graph.py` — remove v2 graph + nodes
- Delete: `backend/app/agents/orchestrator.py`
- Delete: `backend/app/agents/semantic_mapper.py`

**Purpose:** Remove all Phase 1/2 deprecated code once v3 is stable and validated.

- [ ] **Step 1: Verify v3 passes ALL integration tests first**

```bash
cd backend && TESTING=1 python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```
Precondition: ALL PASS

- [ ] **Step 2: Remove v2 graph nodes from graph.py**

Keep only v3-related functions: `build_v3_graph()`, `_run_v3_agent()`, `_v3_response_formatter_node()`, `run_agent_with_ag_ui()`. Remove: `orchestrator_node`, `sql_specialist_node`, `sql_verifier_node`, `sql_executor_node`, `knowledge_specialist_node`, `general_specialist_node`, `response_formatter_node`, `ask_user_clarification_node`, `_last_user_message`, `build_graph`.

- [ ] **Step 3: Update run_agent_with_ag_ui() to always use v3**

```python
async def run_agent_with_ag_ui(
    user_message: str,
    conversation_id: str,
    model: str,
    db_connection_id: str | None = None,
) -> AsyncIterator[str]:
    """Run v3 ReAct Agent graph with AG-UI streaming SSE output."""
    async for event in _run_v3_agent(user_message, conversation_id, model, db_connection_id):
        yield event
```

- [ ] **Step 4: Update state.py to v3-only**

Remove `AgentState` (v2 TypedDict), keep only `ReActState`, `V3AgentState`, and sub-states. Update `AgentStateType` to point to `V3AgentState`.

- [ ] **Step 5: Delete deprecated files**

```bash
rm backend/app/agents/orchestrator.py
rm backend/app/agents/semantic_mapper.py
```

- [ ] **Step 6: Update test imports**

Update any test that imports from `orchestrator` or `semantic_mapper`:
- `tests/test_agents/test_orchestrator.py` → update to test supervisor agent routing
- `tests/semantic_mapper/test_agent.py` → update to test SQL agent tools
- `tests/semantic_mapper/test_tools.py` → update to test tool classes directly

- [ ] **Step 7: Run full test suite**

```bash
cd backend && TESTING=1 python -m pytest tests/ -v --tb=short 2>&1 | tail -10
```
Expected: ALL passing

- [ ] **Step 8: Run lint**

```bash
cd backend && ruff check app/agents/
```
Expected: No errors

- [ ] **Step 9: Final commit**

```bash
git add -A && git commit -m "refactor: Phase 3 cleanup — remove v2 code, finalize v3 ReAct architecture"
```

---

## Verification Summary

After ALL tasks complete, run:

```bash
# Backend tests
cd backend && TESTING=1 python -m pytest tests/ -v --tb=short

# Backend lint
cd backend && ruff check app/agents/ app/gateway/

# Frontend type check
cd frontend && npx vue-tsc --noEmit

# Manual smoke test
curl -X POST http://localhost:8000/api/chat/stream \
  -H "Content-Type: application/json" \
  -d '{"message": "查询数据库状态", "conversation_id": "test-v3"}' \
  --no-buffer
```
