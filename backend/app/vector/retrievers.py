"""Qdrant 向量检索实现：Schema / Example / Knowledge / ErrorCode。"""

from __future__ import annotations

import logging

from qdrant_client.models import FieldCondition, Filter, MatchValue

from app.config import get_settings
from app.protocols import (
    KnowledgeChunk,
    SQLExample,
    TableSchema,
)
from app.vector.client import get_qdrant_manager
from app.vector.embedder import get_embedder

logger = logging.getLogger(__name__)


class QdrantSchemaRetriever:
    """SchemaRetriever Phase 3 实现：基于向量相似度检索相关表 schema。"""

    async def retrieve(self, query: str, db_id: str) -> list[TableSchema]:
        embedder = get_embedder()
        qdrant = get_qdrant_manager().client
        collection = get_settings().models_config.get("collections", {}).get("schemas", "schemas")

        try:
            embeddings = await embedder.embed([query])
            results = await qdrant.search(
                collection_name=collection,
                query_vector=embeddings[0],
                query_filter=Filter(must=[FieldCondition(key="db_id", match=MatchValue(value=db_id))]),
                limit=10,
            )
            schemas = []
            for r in results:
                payload = r.payload or {}
                schemas.append(
                    TableSchema(
                        table_name=payload.get("table_name", ""),
                        ddl=payload.get("ddl", ""),
                        description=payload.get("description", ""),
                        columns=payload.get("columns", []),
                    )
                )
            if schemas:
                logger.info("Schema Linking: 检索到 %d 个相关表", len(schemas))
                return schemas
        except Exception as e:
            logger.warning("QdrantSchemaRetriever 失败: %s", e)

        # 降级：返回空列表（调用方应回退到 DbSchemaRetriever 全量返回）
        return []


class QdrantExampleRetriever:
    """ExampleRetriever Phase 3 实现：基于向量相似度动态检索 SQL 示例。"""

    async def retrieve(self, query: str, top_k: int = 5) -> list[SQLExample]:
        embedder = get_embedder()
        qdrant = get_qdrant_manager().client
        collection = get_settings().models_config.get("collections", {}).get("sql_examples", "sql_examples")

        try:
            embeddings = await embedder.embed([query])
            results = await qdrant.search(
                collection_name=collection,
                query_vector=embeddings[0],
                limit=top_k,
            )
            examples = []
            for r in results:
                payload = r.payload or {}
                examples.append(
                    SQLExample(
                        question=payload.get("question", ""),
                        sql=payload.get("sql", ""),
                        tables=payload.get("tables", []),
                        pattern=payload.get("pattern", ""),
                        difficulty=payload.get("difficulty", "medium"),
                    )
                )
            if examples:
                logger.info("Few-shot 检索: 返回 %d 条相关示例", len(examples))
                return examples
        except Exception as e:
            logger.warning("QdrantExampleRetriever 失败: %s", e)

        # 降级：返回空列表（调用方应回退到 FileExampleRetriever）
        return []


class QdrantKnowledgeRetriever:
    """KnowledgeRetriever Phase 3 实现：基于向量相似度的 RAG 检索。"""

    async def retrieve(self, query: str, category: str | None = None) -> list[KnowledgeChunk]:
        embedder = get_embedder()
        qdrant = get_qdrant_manager().client
        collection = get_settings().models_config.get("collections", {}).get("knowledge", "knowledge")

        try:
            embeddings = await embedder.embed([query])
            search_filter = None
            if category:
                search_filter = Filter(must=[FieldCondition(key="category", match=MatchValue(value=category))])

            results = await qdrant.search(
                collection_name=collection,
                query_vector=embeddings[0],
                query_filter=search_filter,
                limit=5,
            )
            chunks = []
            for r in results:
                payload = r.payload or {}
                chunks.append(
                    KnowledgeChunk(
                        content=payload.get("content", ""),
                        source=payload.get("source", ""),
                        category=payload.get("category", ""),
                    )
                )
            if chunks:
                logger.info("RAG 检索: 返回 %d 条知识", len(chunks))
                return chunks
        except Exception as e:
            logger.warning("QdrantKnowledgeRetriever 失败: %s", e)

        # 降级：返回空列表（调用方应回退到 FileKnowledgeRetriever）
        return []
