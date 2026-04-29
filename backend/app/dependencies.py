"""FastAPI dependency injection bindings.
Upgrade path: Phase 3 swap File* implementations for Qdrant* here only.
"""

from __future__ import annotations

import logging
from functools import lru_cache

from app.knowledge.loader import DbSchemaRetriever, FileExampleRetriever, FileKnowledgeRetriever
from app.llm.client import LiteLLMClientImpl
from app.protocols import ExampleRetriever, KnowledgeRetriever, LLMClient, SchemaRetriever

logger = logging.getLogger(__name__)

# ── Phase 1 基础实现（作为降级回退）──────────────────────────────────────────────


@lru_cache
def _get_file_example_retriever() -> FileExampleRetriever:
    return FileExampleRetriever()


@lru_cache
def _get_file_knowledge_retriever() -> FileKnowledgeRetriever:
    return FileKnowledgeRetriever()


# ── Phase 3 Qdrant 实现（带自动降级）──────────────────────────────────────────────


def get_schema_retriever(db_session=None) -> SchemaRetriever:
    """SchemaRetriever：优先 Qdrant 向量检索，未命中时回退全量 DB DDL。"""
    from app.vector.client import is_qdrant_available

    # 如果 lifespan 中已确认 Qdrant 不可用，直接返回 DB 全量模式
    if not is_qdrant_available():
        if db_session is None:
            raise RuntimeError("DbSchemaRetriever 需要 db_session，但当前上下文未提供")
        return DbSchemaRetriever(db_session)

    # Qdrant 标记为可用时，返回带降级能力的 wrapper
    return _QdrantSchemaRetrieverWithFallback(db_session)


class _QdrantSchemaRetrieverWithFallback:
    """包装器：先尝试 Qdrant 向量检索，返回空则回退到 DbSchemaRetriever 全量。"""

    def __init__(self, db_session) -> None:
        self._qdrant = None
        self._db_fallback = None
        if db_session is not None:
            self._db_fallback = DbSchemaRetriever(db_session)
        try:
            from app.vector.retrievers import QdrantSchemaRetriever

            self._qdrant = QdrantSchemaRetriever()
        except Exception as e:
            logger.debug("QdrantSchemaRetriever 实例化失败: %s", e)

    async def retrieve(self, query: str, db_id: str) -> list:
        if self._qdrant is not None:
            try:
                results = await self._qdrant.retrieve(query, db_id)
                if results:
                    return results
            except Exception as e:
                logger.warning("Qdrant schema 检索失败，回退到全量: %s", e)

        if self._db_fallback is not None:
            return await self._db_fallback.retrieve(query, db_id)

        return []


def get_example_retriever() -> ExampleRetriever:
    """ExampleRetriever：优先 Qdrant 动态检索，失败时回退到文件前 top_k 条。"""
    from app.vector.client import is_qdrant_available

    if not is_qdrant_available():
        return _get_file_example_retriever()
    return _QdrantExampleRetrieverWithFallback()


class _QdrantExampleRetrieverWithFallback:
    """包装器：先尝试 Qdrant 向量检索，返回空则回退到 FileExampleRetriever。"""

    def __init__(self) -> None:
        self._qdrant = None
        self._file_fallback = _get_file_example_retriever()
        try:
            from app.vector.retrievers import QdrantExampleRetriever

            self._qdrant = QdrantExampleRetriever()
        except Exception as e:
            logger.debug("QdrantExampleRetriever 实例化失败: %s", e)

    async def retrieve(self, query: str, top_k: int = 5) -> list:
        if self._qdrant is not None:
            try:
                results = await self._qdrant.retrieve(query, top_k)
                if results:
                    return results
            except Exception as e:
                logger.warning("Qdrant example 检索失败，回退到文件: %s", e)

        return await self._file_fallback.retrieve(query, top_k)


def get_knowledge_retriever() -> KnowledgeRetriever:
    """KnowledgeRetriever：优先 Qdrant RAG 检索，失败时回退到文件关键词匹配。"""
    from app.vector.client import is_qdrant_available

    if not is_qdrant_available():
        return _get_file_knowledge_retriever()
    return _QdrantKnowledgeRetrieverWithFallback()


class _QdrantKnowledgeRetrieverWithFallback:
    """包装器：先尝试 Qdrant 向量检索，返回空则回退到 FileKnowledgeRetriever。"""

    def __init__(self) -> None:
        self._qdrant = None
        self._file_fallback = _get_file_knowledge_retriever()
        try:
            from app.vector.retrievers import QdrantKnowledgeRetriever

            self._qdrant = QdrantKnowledgeRetriever()
        except Exception as e:
            logger.debug("QdrantKnowledgeRetriever 实例化失败: %s", e)

    async def retrieve(self, query: str, category: str | None = None) -> list:
        if self._qdrant is not None:
            try:
                results = await self._qdrant.retrieve(query, category)
                if results:
                    return results
            except Exception as e:
                logger.warning("Qdrant knowledge 检索失败，回退到文件: %s", e)

        return await self._file_fallback.retrieve(query, category)


def get_llm_client(model: str | None = None, task_type: str = "general") -> LLMClient:
    """Create LLM client per request, with optional model override and task type."""
    return LiteLLMClientImpl(model=model, task_type=task_type)
