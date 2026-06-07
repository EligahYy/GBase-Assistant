"""Qdrant 向量检索实现：Schema / Knowledge / ErrorCode。"""

from __future__ import annotations

import logging

from qdrant_client.models import FieldCondition, Filter, MatchValue

from app.config import get_settings
from app.protocols import KnowledgeChunk, TableSchema
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
            response = await qdrant.query_points(
                collection_name=collection,
                query=embeddings[0],
                query_filter=Filter(must=[FieldCondition(key="db_id", match=MatchValue(value=db_id))]),
                limit=10,
            )
            results = response.points if response else []
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

            response = await qdrant.query_points(
                collection_name=collection,
                query=embeddings[0],
                query_filter=search_filter,
                limit=5,
            )
            results = response.points if response else []
            chunks = []
            for r in results:
                payload = r.payload or {}
                chunks.append(
                    KnowledgeChunk(
                        content=payload.get("content", ""),
                        source=payload.get("title") or payload.get("source_file") or payload.get("source", ""),
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
