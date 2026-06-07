"""FastAPI dependency injection bindings.
Upgrade path: Phase 3 swap File* implementations for Qdrant* here only.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Any

from app.knowledge.loader import DbSchemaRetriever, FileKnowledgeRetriever
from app.llm.client import LiteLLMClientImpl
from app.observability import metrics
from app.protocols import KnowledgeRetriever, LLMClient, SchemaRetriever

logger = logging.getLogger(__name__)

# ── Phase 1 基础实现（作为降级回退）──────────────────────────────────────────────


@lru_cache
def _get_file_knowledge_retriever() -> FileKnowledgeRetriever:
    return FileKnowledgeRetriever()


# ── Phase 3 泛型降级检索器────────────────────────────────────────────────────────


class FallbackRetriever:
    """泛型降级检索器：先尝试 primary retriever，空结果或异常则回退到 fallback。

    对调用方透明（实现 retrieve() 方法），chain 层无感知差异。
    """

    def __init__(
        self,
        primary: Any | None,
        fallback: Any | None,
        name: str = "retriever",
    ) -> None:
        self._primary = primary
        self._fallback = fallback
        self._name = name

    async def retrieve(self, *args: Any, **kwargs: Any) -> list[Any]:
        if self._primary is not None:
            try:
                results = await self._primary.retrieve(*args, **kwargs)
                if results:
                    metrics.record_vector_retrieval(self._name, hit=True)
                    return results
                metrics.record_vector_retrieval(self._name, hit=False)
            except Exception as e:
                logger.warning("%s primary 失败，回退: %s", self._name, e)
                metrics.record_vector_retrieval(self._name, hit=False)
        if self._fallback is not None:
            return await self._fallback.retrieve(*args, **kwargs)
        return []


# ── Phase 3 Qdrant 实现（带自动降级）──────────────────────────────────────────────


def get_schema_retriever(db_session=None) -> SchemaRetriever:
    """SchemaRetriever：优先 Qdrant 向量检索，未命中时回退全量 DB DDL。"""
    from app.vector.client import is_qdrant_available

    if not is_qdrant_available():
        if db_session is None:
            raise RuntimeError("DbSchemaRetriever 需要 db_session，但当前上下文未提供")
        return DbSchemaRetriever(db_session)

    primary = None
    try:
        from app.vector.retrievers import QdrantSchemaRetriever

        primary = QdrantSchemaRetriever()
    except Exception as e:
        logger.debug("QdrantSchemaRetriever 实例化失败: %s", e)

    fallback = DbSchemaRetriever(db_session) if db_session is not None else None
    return FallbackRetriever(
        primary=primary,
        fallback=fallback,
        name="SchemaRetriever",
    )  # type: ignore[return-value]


def get_knowledge_retriever() -> KnowledgeRetriever:
    """KnowledgeRetriever：混合检索（Qdrant + ripgrep），双路径互补兜底。"""
    from app.vector.client import is_qdrant_available

    # 构建 Qdrant 检索器（可选）
    vector = None
    if is_qdrant_available():
        try:
            from app.vector.retrievers import QdrantKnowledgeRetriever

            vector = QdrantKnowledgeRetriever()
        except Exception as e:
            logger.debug("QdrantKnowledgeRetriever 实例化失败: %s", e)

    # 构建 Grep 检索器
    from app.config import get_settings
    from app.vector.grep_retriever import GrepRetriever

    grep = GrepRetriever(get_settings().knowledge_dir)

    # 混合检索器（内部分流 + 互补兜底）
    from app.vector.hybrid_retriever import HybridKnowledgeRetriever

    hybrid = HybridKnowledgeRetriever(vector=vector, grep=grep)

    # 最外层兜底：Hybrid 整体失败时回退到 FileKnowledgeRetriever
    return FallbackRetriever(
        primary=hybrid,
        fallback=_get_file_knowledge_retriever(),
        name="KnowledgeRetriever",
    )  # type: ignore[return-value]


def get_llm_client(model: str | None = None, task_type: str = "general") -> LLMClient:
    """Create LLM client per request, with optional model override and task type."""
    return LiteLLMClientImpl(model=model, task_type=task_type)
