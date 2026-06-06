"""SearchKnowledgeTool — retrieves knowledge base content.

Wraps HybridKnowledgeRetriever from app.dependencies.get_knowledge_retriever().
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.tools.base import ToolParameter

logger = logging.getLogger(__name__)


class SearchKnowledgeTool:
    """Tool: search the GBase 8a knowledge base (official manuals + web content)."""

    def __init__(self) -> None:
        pass

    @property
    def name(self) -> str:
        return "search_knowledge"

    @property
    def description(self) -> str:
        return (
            "Search the GBase 8a knowledge base for official documentation content. "
            "Returns relevant chunks from product manuals, dialect rules, "
            "and other technical documentation."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="The question or keywords to search for in the knowledge base",
            ),
        ]

    async def execute(self, query: str = "", **kwargs: Any) -> Any:
        """Search the knowledge base via HybridKnowledgeRetriever.

        Args:
            query: The search query.

        Returns:
            list[KnowledgeChunk] of matching results.
        """
        q = query or kwargs.get("query", "")
        if not q:
            return []

        from app.dependencies import get_knowledge_retriever

        retriever = get_knowledge_retriever()
        chunks = await retriever.retrieve(q)
        return chunks

    def format_result(self, result: Any) -> dict:
        """Format knowledge search results for display.

        Args:
            result: list[KnowledgeChunk] from execute().

        Returns:
            {"summary": str, "detail": list[dict]|None, "truncated": bool}
        """
        if not result:
            return {
                "summary": "未找到相关文档内容。",
                "detail": None,
                "truncated": False,
            }

        count = len(result)
        sources = list({c.source for c in result if c.source})
        summary = f"检索到 {count} 条相关文档（来自 {len(sources)} 个来源）"

        truncated = count > 5
        detail_chunks = result[:5] if truncated else result
        detail = [
            {
                "content": c.content[:500] + "..." if len(c.content) > 500 else c.content,
                "source": c.source,
                "category": c.category,
            }
            for c in detail_chunks
        ]

        return {
            "summary": summary,
            "detail": detail,
            "truncated": truncated,
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
