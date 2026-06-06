"""Semantic Mapper Agent — ReAct Agent + 4 tools, maps business terms to schema objects."""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any

import yaml
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult, ChatGeneration

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


# 🆕 Tool 5: Database Status
def _make_get_database_status_tool(db_connection_id: str):
    from app.database import async_session_factory
    from sqlalchemy import select
    from app.models.connection import DbConnection
    from app.db_connectors.connector_factory import get_connector
    from app.api.connections import _to_connection_config
    from app.sql.sandbox import SQLSandbox

    async def get_database_status() -> str:
        """Query database runtime status: connection count, active queries, uptime, table summary. Uses pre-defined system table queries — no SQL generation needed."""
        import asyncio

        if not db_connection_id:
            return json.dumps({"error": "未选择数据库连接"}, ensure_ascii=False)

        async with async_session_factory() as session:
            result = await session.execute(select(DbConnection).where(DbConnection.id == db_connection_id))
            conn = result.scalar_one_or_none()
        if not conn:
            return json.dumps({"error": "连接不存在"}, ensure_ascii=False)

        connector = get_connector(conn.driver_type)
        config = _to_connection_config(conn)

        queries = {
            "连接数": "SELECT COUNT(*) AS cnt FROM information_schema.PROCESSLIST",
            "活跃SQL": "SELECT id, user, host, db, time, state, LEFT(info,200) AS info FROM information_schema.PROCESSLIST WHERE time > 0",
            "运行时间": "SELECT DATEDIFF(NOW(), MIN(create_time)) AS running_days FROM information_schema.TABLES",
            "表概况": "SELECT TABLE_NAME, TABLE_ROWS, ROUND(DATA_LENGTH/1024/1024,2) AS size_mb FROM information_schema.TABLES WHERE TABLE_SCHEMA=DATABASE() ORDER BY DATA_LENGTH DESC LIMIT 20",
        }

        async def _run_one(label: str, sql: str) -> dict:
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

    return get_database_status


# 🆕 Tool 6: Error Code Lookup
def _make_query_error_code_tool():
    from app.config import get_settings
    from app.vector.client import get_qdrant_manager
    from app.vector.embedder import get_embedder

    async def query_error_code(query: str, top_k: int = 5) -> str:
        """Search GBase 8a error codes by semantic similarity. Returns error code, description, and solution."""
        try:
            embedder = get_embedder()
            qdrant = get_qdrant_manager().client
            collection = get_settings().models_config.get("collections", {}).get("error_codes", "error_codes")

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

    return query_error_code


def build_semantic_mapper_tools(glossary: dict, db_id: str):
    """Build the 6-tool set for the Semantic Mapper Agent (backward-compatible).

    Returns tools from ToolRegistry. Falls back to closure-based tools if
    registry is empty (e.g., in tests without full app context).
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


# ── LangChain Adapter for LiteLLMClientImpl ──────────────────────────────────────

class _LiteLLMChatAdapter(BaseChatModel):
    """Wraps LiteLLMClientImpl to satisfy LangChain BaseChatModel interface."""

    llm_client: Any
    _bound_tools: list | None = None

    def __init__(self, llm_client):
        from langchain_core.language_models import BaseChatModel
        super().__init__(llm_client=llm_client)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError("Use async version")

    async def _agenerate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        dict_msgs = []
        for m in messages:
            if hasattr(m, "type"):
                role = "assistant" if m.type == "ai" else ("system" if m.type == "system" else "user")
            else:
                role = "user"
            dict_msgs.append({"role": role, "content": str(m.content)})

        tools = kwargs.pop("tools", None) or self._bound_tools
        if tools:
            kwargs["tools"] = [t if isinstance(t, dict) else {"type": "function", "function": {"name": t.name, "description": t.description, "parameters": t.args_schema.schema() if t.args_schema else {}}} for t in tools]

        content, _ = await self.llm_client.complete(dict_msgs, **kwargs)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])

    def bind_tools(self, tools: list, **kwargs):
        clone = _LiteLLMChatAdapter(self.llm_client)
        clone._bound_tools = tools
        return clone

    @property
    def _llm_type(self) -> str:
        return "litellm-adapter"

    @property
    def _identifying_params(self):
        return {}


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
        return {"business_terms": None, "chart_config": None, "retrieved_schemas": None}

    db_id = state.get("db_connection_id") or ""

    # 🆕 Quick path: monitoring questions bypass NL2SQL pipeline
    # Must run BEFORE any expensive operations (glossary, schema graph, vector search)
    _MONITORING_PATTERNS = [
        "连接状态", "连接数", "多少条", "sql在跑", "运行了多久",
        "数据库状态", "慢查询", "连接信息", "数据库连接",
    ]
    is_monitoring = any(p in user_msg.lower() for p in _MONITORING_PATTERNS)

    if is_monitoring:
        if not db_id:
            return {
                "grounding": {"tables": [], "columns": {}, "join_paths": [], "confidence": 0.0, "matches": 0},
                "business_terms": {},
                "chart_config": None,
                "retrieved_schemas": None,
                "final_response": "当前未选择数据库连接。请先在左侧设置中添加并选择一个 GBase 8a 数据库连接，然后再查询数据库状态。",
            }
        status_tool = _make_get_database_status_tool(db_id)
        raw_json = await status_tool()
        try:
            status_data = json.loads(raw_json)
            lines = ["**数据库状态概览**\n"]
            for label, data in status_data.items():
                if isinstance(data, dict) and "error" in data:
                    lines.append(f"### {label}\n> 错误: {data['error']}")
                elif isinstance(data, dict) and data.get("rows") and data["rows"]:
                    cols = data["columns"]
                    line = f"### {label}"
                    if len(cols) == 1 and data["row_count"] == 1:
                        line += f"\n{cols[0]}: **{data['rows'][0][0]}**"
                    else:
                        line += f"\n| {' | '.join(cols)} |"
                        line += f"\n|{'|'.join(['---' for _ in cols])}|"
                        for row in data["rows"][:20]:
                            line += f"\n| {' | '.join(str(c) for c in row)} |"
                    lines.append(line)
                else:
                    lines.append(f"### {label}\n> 无数据")
            formatted = "\n\n".join(lines)
        except (json.JSONDecodeError, TypeError):
            formatted = f"数据库状态查询结果:\n{raw_json}"
        return {
            "grounding": {"tables": [], "columns": {}, "join_paths": [], "confidence": 1.0, "matches": 0},
            "business_terms": {},
            "chart_config": None,
            "retrieved_schemas": None,
            "final_response": formatted,
        }

    glossary = load_glossary()
    glossary_hits = _match_glossary_term(user_msg, glossary)

    from app.agents.schema_graph import get_schema_graph
    graph_inst = get_schema_graph(db_id)
    schema_text = ""
    if graph_inst._built:
        schema_text = _build_schema_context(graph_inst.tables)

    # Pre-fetch vector search results (also used by sql_specialist)
    retrieved_schemas = None
    if db_id:
        try:
            from app.dependencies import get_schema_retriever
            from app.database import async_session_factory
            async with async_session_factory() as session:
                retriever = get_schema_retriever(session)
                retrieved_schemas = await retriever.retrieve(user_msg, db_id)
        except Exception:
            pass

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

        chat_model = _LiteLLMChatAdapter(llm_client)
        agent = create_react_agent(
            model=chat_model,
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
            "retrieved_schemas": retrieved_schemas,
        }
    except Exception as e:
        logger.error("Semantic Mapper failed: %s", e)
        return {
            "grounding": {"tables": [], "columns": {}, "join_paths": [], "confidence": 0.0},
            "business_terms": None,
            "chart_config": None,
            "retrieved_schemas": None,
        }
