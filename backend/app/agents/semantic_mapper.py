"""Semantic Mapper Agent — ReAct Agent + 4 tools, maps business terms to schema objects."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml

from app.agents.state import AgentStateType

logger = logging.getLogger(__name__)

# ── Glossary Loading ─────────────────────────────────────────────────────────────

_glossary_loaded = False


def _get_glossary_path() -> str:
    return str(Path(__file__).parent.parent.parent / "config" / "glossary.yaml")


def load_glossary(path: str | None = None) -> dict:
    """Load business glossary from YAML. Returns {term: {table, column, synonyms}}."""
    filepath = path or _get_glossary_path()
    if not Path(filepath).exists():
        logger.warning("Glossary file not found: %s", filepath)
        return {}
    with open(filepath, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f) or {}
    glossary = data.get("terms", {}) or {}
    logger.info("Glossary loaded: %d terms from %s", len(glossary), filepath)
    return glossary


def _match_glossary_term(query: str, glossary: dict) -> list[dict]:
    """Match business terms in query against glossary keys and synonyms."""
    results = []
    if not glossary:
        return results
    for term, info in glossary.items():
        if not isinstance(info, dict):
            continue
        if term in query:
            results.append({
                "term": term,
                "table": info.get("table", ""),
                "column": info.get("column", ""),
                "sql_template": info.get("sql_template"),
                "score": 1.0,
                "source": "glossary",
            })
            continue
        synonyms = info.get("synonyms", []) or []
        for syn in synonyms:
            if syn in query:
                results.append({
                    "term": term,
                    "synonym": syn,
                    "table": info.get("table", ""),
                    "column": info.get("column", ""),
                    "sql_template": info.get("sql_template"),
                    "score": 1.0,
                    "source": "glossary",
                })
                break
    return results


# ── Schema Context Builder ────────────────────────────────────────────────────────

def _build_schema_context(
    tables: dict[str, Any],
    table_names: list[str] | None = None,
) -> str:
    """Build a readable schema description for the agent prompt."""
    if not tables:
        return "（无可用 Schema 信息）"
    lines = []
    target = table_names if table_names else list(tables.keys())
    for name in target:
        table = tables.get(name)
        if not table:
            continue
        label = getattr(table, "label", "") or ""
        line = f"\n表: {name}"
        if label:
            line += f" ({label})"
        lines.append(line)
        for col in table.columns:
            col_info = f"  - {col.name} ({col.data_type})"
            if col.role and col.role != "UNKNOWN":
                col_info += f" [{col.role}]"
            if col.label:
                col_info += f" -- {col.label}"
            if col.enum_values:
                enum_str = ", ".join(f"{k}={v}" for k, v in col.enum_values.items())
                col_info += f" (枚举: {enum_str})"
            if col.comment and col.comment != col.label:
                col_info += f" ({col.comment})"
            lines.append(col_info)
    return "\n".join(lines)


# ── Tool Factories ────────────────────────────────────────────────────────────────

def _make_query_glossary_tool(glossary: dict):
    def query_glossary(term: str) -> str:
        """Search the business glossary for a term. Returns matching (table, column) mappings."""
        results = _match_glossary_term(term, glossary)
        if not results:
            return "未找到匹配的业务术语。"
        lines = ["匹配的业务术语:"]
        for r in results:
            line = f"  - {r['term']} -> {r['table']}.{r['column']}"
            if r.get("sql_template"):
                line += f" (SQL template: {r['sql_template']})"
            if r.get("synonym"):
                line += f" (matched via synonym '{r['synonym']}')"
            lines.append(line)
        return "\n".join(lines)
    return query_glossary


def _make_search_schema_semantic_tool(db_id: str):
    from app.dependencies import get_schema_retriever
    from app.database import async_session_factory

    async def search_schema_semantic(query: str) -> str:
        """Search for database tables relevant to the natural language query. Returns top-k tables with DDL."""
        async with async_session_factory() as session:
            retriever = get_schema_retriever(session)
            schemas = await retriever.retrieve(query, db_id)
        if not schemas:
            return "未找到相关表。"
        lines = ["语义检索结果 (top-k 相关表):"]
        for i, s in enumerate(schemas):
            desc = f" ({s.description})" if s.description else ""
            lines.append(f"  {i+1}. {s.table_name}{desc}")
            if s.ddl:
                ddl_short = s.ddl[:200] + "..." if len(s.ddl) > 200 else s.ddl
                lines.append(f"     DDL: {ddl_short}")
        return "\n".join(lines)
    return search_schema_semantic


def _make_get_table_profile_tool(db_id: str):
    from app.agents.schema_graph import get_schema_graph

    def get_table_profile(table_name: str) -> str:
        """Get complete column info for a table (names, types, comments, enum values, roles, relationships)."""
        graph = get_schema_graph(db_id)
        if not graph._built:
            loaded = type(graph).load(db_id)
            if loaded:
                from app.agents.schema_graph import _graph_instances
                _graph_instances[db_id] = loaded
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
    return get_table_profile


def _make_find_join_path_tool(db_id: str):
    from app.agents.schema_graph import get_schema_graph

    def find_join_path(table_a: str, table_b: str) -> str:
        """Find JOIN path between two tables. Returns FK-based JOIN conditions."""
        graph = get_schema_graph(db_id)
        if not graph._built:
            loaded = type(graph).load(db_id)
            if loaded:
                from app.agents.schema_graph import _graph_instances
                _graph_instances[db_id] = loaded
                graph = loaded
        path = graph.find_join_path(table_a, table_b)
        if not path:
            return f"No JOIN path found between {table_a} and {table_b}."
        lines = [f"JOIN path ({len(path)} steps):"]
        for i, rel in enumerate(path):
            lines.append(f"  {i+1}. {rel['via']} (confidence: {rel['confidence']})")
        return "\n".join(lines)
    return find_join_path


def build_semantic_mapper_tools(glossary: dict, db_id: str):
    """Build the 4-tool set for the Semantic Mapper Agent."""
    return [
        _make_query_glossary_tool(glossary),
        _make_search_schema_semantic_tool(db_id),
        _make_get_table_profile_tool(db_id),
        _make_find_join_path_tool(db_id),
    ]


# ── System Prompt ─────────────────────────────────────────────────────────────────

SEMANTIC_MAPPER_SYSTEM = """You are a database semantic mapping expert. Your job is to map a user's natural language question to the correct database tables and columns.

## Workflow

1. **First, use query_glossary()** to look up known business term mappings
2. **Then, use search_schema_semantic()** to find tables for terms not in the glossary
3. **For candidate tables, call get_table_profile()** to get the full column structure
4. **If multiple tables are needed, call find_join_path()** to find JOIN paths
5. **Output structured JSON** with all mapping results

## Constraints

1. **Schema-First Principle**: All mappings MUST reference real tables/columns. If unsure, call get_table_profile() to confirm. NEVER guess column names.
2. **Confidence Self-Assessment**: You MUST output a confidence score (0-1):
   - >=0.9: Glossary exact match + schema cross-validation passed
   - 0.7-0.9: Inferred from column names + COMMENT labels, high semantic match
   - 0.5-0.7: Vector semantic similarity only, needs confirmation
   - <0.5: Cannot map, mark as unknown
3. **Step-by-step Validation**: Verify each observation before proceeding.
4. **Chart Awareness**: If the user mentions a chart type (柱状图/折线图/饼图/散点图), record it in chart_hint.
5. **Time Expression Handling**: Recognize "最近一个月", "本月", "上季度" etc., generate corresponding SQL templates.

## Output Format (strict JSON)

```json
{
  "tables": ["table1", "table2"],
  "columns": {"table1": ["col1", "col2"], "table2": ["col3"]},
  "business_terms": {
    "销售额": {"table": "table1", "column": "col2"},
    "最近一个月": {"sql_template": "table1.created_at >= CURDATE() - INTERVAL 1 MONTH"}
  },
  "join_paths": ["table1.fk_id = table2.id"],
  "chart_hint": {"type": "bar", "x": "产品线", "y": "销售额"},
  "unresolved_terms": [],
  "confidence": 0.92
}
```
"""


# ── LangGraph Node ────────────────────────────────────────────────────────────────

async def semantic_mapper_node(state: AgentStateType) -> dict:
    """LangGraph node: Run the Semantic Mapper ReAct Agent."""
    from app.dependencies import get_llm_client
    from langgraph.prebuilt import create_react_agent
    from langchain_core.messages import HumanMessage, SystemMessage

    msgs = state.get("messages", [])
    user_msg = ""
    if msgs:
        last = msgs[-1]
        if hasattr(last, "content"):
            user_msg = last.content if isinstance(last.content, str) else str(last.content)
        elif isinstance(last, dict):
            user_msg = last.get("content", "")
    if not user_msg:
        return {"business_terms": None, "chart_config": None}

    db_id = state.get("db_connection_id") or ""

    glossary = load_glossary()
    glossary_hits = _match_glossary_term(user_msg, glossary)

    from app.agents.schema_graph import get_schema_graph
    graph_inst = get_schema_graph(db_id)
    schema_text = ""
    if graph_inst._built:
        schema_text = _build_schema_context(graph_inst.tables)

    try:
        llm_client = get_llm_client(task_type="sql")
        tools = build_semantic_mapper_tools(glossary, db_id)

        full_prompt = SEMANTIC_MAPPER_SYSTEM
        if schema_text:
            full_prompt += f"\n\n## Current Database Schema\n{schema_text}"
        if glossary_hits:
            hits_text = "\n".join(
                f"  - {h['term']} -> {h['table']}.{h['column']}"
                for h in glossary_hits
            )
            full_prompt += f"\n\n## Pre-matched Glossary Terms (use these directly)\n{hits_text}"

        full_prompt += f"\n\n## User Question\n{user_msg}\n\nFollow the workflow step by step, then output JSON."

        messages = [
            SystemMessage(content=full_prompt),
            HumanMessage(content=user_msg),
        ]

        agent = create_react_agent(
            model=llm_client,
            tools=tools,
            state_modifier=full_prompt,
        )

        result = await agent.ainvoke({"messages": messages})

        output_messages = result.get("messages", [])
        mapping = None
        for msg in reversed(output_messages):
            if hasattr(msg, "content") and isinstance(msg.content, str):
                json_match = re.search(r'\{[\s\S]*\}', msg.content)
                if json_match:
                    try:
                        mapping = json.loads(json_match.group(0))
                        if "tables" in mapping:
                            break
                    except json.JSONDecodeError:
                        continue

        if not mapping:
            table_hits = set()
            column_hits: dict[str, list[str]] = {}
            for h in glossary_hits:
                table_hits.add(h["table"])
                column_hits.setdefault(h["table"], []).append(h["column"])
            mapping = {
                "tables": list(table_hits),
                "columns": column_hits,
                "business_terms": {h["term"]: {"table": h["table"], "column": h["column"]} for h in glossary_hits},
                "join_paths": [],
                "chart_hint": None,
                "unresolved_terms": [],
                "confidence": 0.6 if glossary_hits else 0.3,
            }

        logger.info("Semantic Mapper: confidence=%.2f, tables=%s",
                     mapping.get("confidence", 0), mapping.get("tables", []))

        return {
            "grounding": {
                "tables": mapping.get("tables", []),
                "columns": mapping.get("columns", {}),
                "join_paths": mapping.get("join_paths", []),
                "confidence": mapping.get("confidence", 0.5),
                "matches": len(mapping.get("tables", [])),
            },
            "business_terms": mapping.get("business_terms", {}),
            "chart_config": mapping.get("chart_hint"),
        }
    except Exception as e:
        logger.error("Semantic Mapper failed: %s", e)
        return {
            "grounding": {"tables": [], "columns": {}, "join_paths": [], "confidence": 0.0},
            "business_terms": None,
            "chart_config": None,
        }
