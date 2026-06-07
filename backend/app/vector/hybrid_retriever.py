# backend/app/vector/hybrid_retriever.py
"""HybridKnowledgeRetriever: Qdrant 向量检索 + ripgrep 精确检索 混合编排。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.protocols import KnowledgeChunk, KnowledgeRetriever

if TYPE_CHECKING:
    from app.vector.grep_retriever import QueryRouter

logger = logging.getLogger(__name__)

RRF_K = 60
TOP_K = 5


def _chunk_key(chunk: KnowledgeChunk) -> str:
    """Identify a chunk without collapsing distinct chapters from the same document."""
    normalized = " ".join(chunk.content.split())
    return f"{chunk.source}|{normalized[:240]}"


def reciprocal_rank_fusion(
    results_a: list[KnowledgeChunk],
    results_b: list[KnowledgeChunk],
    k: int = RRF_K,
    top_k: int = TOP_K,
) -> list[KnowledgeChunk]:
    """Reciprocal Rank Fusion：基于排名的倒数加权融合两个排序列表。

    score(d) = Σ 1/(k + rank_i(d))
    """
    scores: dict[str, float] = {}
    content_map: dict[str, KnowledgeChunk] = {}

    for rank, chunk in enumerate(results_a, 1):
        key = _chunk_key(chunk)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        content_map[key] = chunk

    for rank, chunk in enumerate(results_b, 1):
        key = _chunk_key(chunk)
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        if key not in content_map:
            content_map[key] = chunk

    sorted_keys = sorted(scores, key=lambda kk: scores[kk], reverse=True)
    return [content_map[key] for key in sorted_keys[:top_k]]


class HybridKnowledgeRetriever:
    """混合知识检索器：按查询类型分流到向量或 grep 路径，互补兜底。

    实现 KnowledgeRetriever Protocol，对 chain 层透明。
    """

    def __init__(
        self,
        vector: KnowledgeRetriever | None,
        grep: KnowledgeRetriever | None,
        router: QueryRouter | None = None,
    ) -> None:
        self._vector = vector
        self._grep = grep
        if router is None:
            from app.vector.grep_retriever import QueryRouter as QR

            router = QR()
        self._router = router

    async def retrieve(self, query: str, category: str | None = None) -> list[KnowledgeChunk]:
        qtype = self._router.classify(query)

        if qtype == "precise":
            primary_results = await self._safe_retrieve(self._grep, query, category)
            if primary_results:
                logger.debug("precise 查询走 GrepRetriever，命中 %d 条", len(primary_results))
                return primary_results[:TOP_K]
            fallback_results = await self._safe_retrieve(self._vector, query, category)
            if fallback_results:
                logger.debug("precise 查询 GrepRetriever 未命中，降级到 Qdrant，命中 %d 条", len(fallback_results))
            return fallback_results[:TOP_K]
        else:
            vector_results = await self._safe_retrieve(self._vector, query, category)
            grep_results = await self._safe_retrieve(self._grep, query, category)

            if vector_results and grep_results:
                logger.debug("semantic 查询双路径均有结果，RRF 融合")
                return reciprocal_rank_fusion(vector_results, grep_results)
            elif vector_results:
                logger.debug("semantic 查询走 Qdrant，命中 %d 条", len(vector_results))
                return vector_results[:TOP_K]
            elif grep_results:
                logger.debug("semantic 查询 Qdrant 未命中，降级到 GrepRetriever，命中 %d 条", len(grep_results))
                return grep_results[:TOP_K]
            return []

    async def _safe_retrieve(
        self,
        retriever: KnowledgeRetriever | None,
        query: str,
        category: str | None,
    ) -> list[KnowledgeChunk]:
        if retriever is None:
            return []
        try:
            return await retriever.retrieve(query, category)
        except Exception as e:
            logger.warning("检索器异常: %s", e)
            return []
