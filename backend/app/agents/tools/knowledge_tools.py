"""SearchKnowledgeTool — retrieves knowledge base content for the unified agent.

Wraps HybridKnowledgeRetriever from app.dependencies.get_knowledge_retriever().
Returns structured results with retrieval status for anti-hallucination guardrails.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.tools.base import ToolParameter

logger = logging.getLogger(__name__)


class SearchKnowledgeTool:
    """Tool: search the GBase 8a knowledge base (official manuals + web content).

    Used by the unified ReAct agent. The agent calls this tool to retrieve
    relevant documentation chunks, then synthesizes the answer itself.
    """

    def __init__(self) -> None:
        pass

    @property
    def name(self) -> str:
        return "search_knowledge"

    @property
    def description(self) -> str:
        return (
            "Search the GBase 8a knowledge base for official documentation. "
            "Returns relevant chunks from product manuals, dialect rules, "
            "and technical documentation. Use this BEFORE answering any GBase 8a "
            "technical question — never answer from your own knowledge. "
            "Check the 'status' field in the result: "
            "'found' means sufficient info, 'partial' means some info, "
            "'not_found' means you MUST say the knowledge base doesn't have this info."
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

    async def execute(self, query: str = "", **kwargs: Any) -> dict:
        """Search the knowledge base via HybridKnowledgeRetriever.

        Returns:
            dict with keys: status (found|partial|not_found), chunks (list[dict]),
            sources (list[str]), summary (str)
        """
        q = query or kwargs.get("query", "")
        if not q:
            return {"status": "not_found", "chunks": [], "sources": [], "summary": "未提供搜索关键词"}

        from app.dependencies import get_knowledge_retriever

        retriever = get_knowledge_retriever()
        raw_chunks = await retriever.retrieve(q)

        if not raw_chunks:
            # Try domain expansion fallback
            from app.agents.agents.knowledge_agent import expand_knowledge_query

            expanded = expand_knowledge_query(q)
            if expanded != q:
                raw_chunks = await retriever.retrieve(expanded)

        if not raw_chunks:
            return {"status": "not_found", "chunks": [], "sources": [], "summary": "未找到相关文档内容"}

        # Classify retrieval quality
        status = "found" if len(raw_chunks) >= 3 else "partial"

        chunks_data = [
            {
                "content": c.content[:2000] if c.content else "",
                "source": c.source or "未知来源",
                "category": getattr(c, "category", ""),
            }
            for c in raw_chunks[:5]
        ]

        sources = list(dict.fromkeys(c["source"] for c in chunks_data))

        return {
            "status": status,
            "chunks": chunks_data,
            "sources": sources,
            "summary": f"检索到 {len(raw_chunks)} 条相关文档 (状态: {status})，来源: {', '.join(sources[:3])}",
        }

    def format_result(self, result: Any) -> dict:
        """Format knowledge search results for display.

        Returns:
            {"summary": str, "detail": dict|None, "truncated": bool}
        """
        if not result or not isinstance(result, dict):
            return {"summary": "未找到相关文档内容。", "detail": None, "truncated": False}

        status = result.get("status", "not_found")
        chunks = result.get("chunks", [])
        sources = result.get("sources", [])

        summary = result.get("summary", f"检索到 {len(chunks)} 条相关文档")
        if status == "not_found":
            summary = "未找到相关文档内容（知识库中无匹配信息）"

        return {
            "summary": summary,
            "detail": {
                "status": status,
                "chunks": chunks,
                "sources": sources,
            },
            "truncated": len(chunks) > 5,
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
