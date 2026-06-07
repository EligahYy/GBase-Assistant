"""QueryGlossaryTool — looks up business terms in the glossary YAML.

Maps business terms to database tables and columns.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

import yaml

from app.agents.tools.base import ToolParameter

logger = logging.getLogger(__name__)


def _get_glossary_path() -> str:
    return str(Path(__file__).parent.parent.parent.parent / "config" / "glossary.yaml")


def _load_glossary(path: str | None = None) -> dict:
    """Load business glossary from YAML. Returns {term: {table, column, synonyms}}."""
    filepath = path or _get_glossary_path()
    if not Path(filepath).exists():
        logger.warning("Glossary file not found: %s", filepath)
        return {}
    with open(filepath, encoding="utf-8") as f:
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


class QueryGlossaryTool:
    """Tool: look up business terms in the glossary."""

    def __init__(self) -> None:
        self._glossary: dict | None = None

    @property
    def name(self) -> str:
        return "query_glossary"

    @property
    def description(self) -> str:
        return (
            "Search the business glossary for a business term or its synonyms. "
            "Returns (table, column) mappings and optional SQL templates."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="term",
                type="string",
                description="The business term to look up in the glossary",
            ),
        ]

    async def execute(self, term: str = "", **kwargs: Any) -> Any:
        """Look up a term in the glossary.

        Args:
            term: The business term to search for.

        Returns:
            list[dict] of matching glossary entries.
        """
        query = term or kwargs.get("term", "")
        if self._glossary is None:
            self._glossary = _load_glossary()
        results = _match_glossary_term(query, self._glossary)
        return results

    def format_result(self, result: Any) -> dict:
        """Format glossary results for display.

        Args:
            result: list[dict] from execute().

        Returns:
            {"summary": str, "detail": list[dict]|None, "truncated": bool}
        """
        if not result:
            return {
                "summary": "未找到匹配的业务术语。",
                "detail": None,
                "truncated": False,
            }

        summary = f"检索到 {len(result)} 个匹配的业务术语"
        detail = []
        for r in result:
            entry = {
                "term": r["term"],
                "table": r.get("table", ""),
                "column": r.get("column", ""),
            }
            if r.get("synonym"):
                entry["matched_via_synonym"] = r["synonym"]
            if r.get("sql_template"):
                entry["sql_template"] = r["sql_template"]
            detail.append(entry)

        return {
            "summary": summary,
            "detail": detail,
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
