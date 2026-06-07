"""LookupErrorCodeTool — searches GBase 8a error codes in Qdrant.

Used by the SQL specialist to interpret database errors.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.tools.base import ToolParameter

logger = logging.getLogger(__name__)


class LookupErrorCodeTool:
    """Tool: search GBase 8a error codes by semantic similarity."""

    def __init__(self) -> None:
        self._qdrant_available: bool | None = None

    @property
    def name(self) -> str:
        return "lookup_error"

    @property
    def description(self) -> str:
        return (
            "Search GBase 8a error codes by semantic similarity. "
            "Returns error code, description, and solution."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="The error code, error message, or keywords to search for",
            ),
        ]

    async def execute(self, query: str = "", **kwargs: Any) -> Any:
        """Search error codes via Qdrant semantic search.

        Args:
            query: The error code, message, or search keywords.

        Returns:
            list[dict] of matching error code entries with code, description, solution.
        """
        q = query or kwargs.get("query", "")
        if not q:
            return []

        try:
            from app.config import get_settings
            from app.vector.client import get_qdrant_manager
            from app.vector.embedder import get_embedder

            embedder = get_embedder()
            qdrant = get_qdrant_manager().client
            collection = get_settings().models_config.get("collections", {}).get(
                "error_codes", "error_codes"
            )

            embeddings = await embedder.embed([q])
            results = await qdrant.query_points(
                collection_name=collection,
                query=embeddings[0],
                limit=5,
            )
            points = results.points if results else []

            if not points:
                return []

            entries = []
            for r in points:
                payload = r.payload or {}
                entries.append({
                    "code": payload.get("code", "?"),
                    "description": payload.get("description", ""),
                    "solution": payload.get("solution", ""),
                    "score": float(r.score) if r.score is not None else 0.0,
                })
            return entries
        except Exception as e:
            logger.warning("Error code search failed: %s", e)
            return []

    def format_result(self, result: Any) -> dict:
        """Format error code results for display.

        Args:
            result: list[dict] from execute().

        Returns:
            {"summary": str, "detail": list[dict]|None, "truncated": bool}
        """
        if not result:
            return {
                "summary": "未找到匹配的错误码。建议查阅 GBase 8a 官方手册。",
                "detail": None,
                "truncated": False,
            }

        top_score = result[0].get("score", 0)
        summary = f"检索到 {len(result)} 个相关错误码 (最高相似度: {top_score:.2f})"

        detail = []
        for entry in result:
            detail.append({
                "code": entry.get("code", ""),
                "description": entry.get("description", ""),
                "solution": entry.get("solution", ""),
                "similarity": entry.get("score", 0),
            })

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
