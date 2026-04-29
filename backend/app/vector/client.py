"""Qdrant async client 封装。"""

from __future__ import annotations

import logging

from qdrant_client import AsyncQdrantClient
from qdrant_client.models import Distance, VectorParams

from app.config import get_settings

logger = logging.getLogger(__name__)

DEFAULT_DIMENSION = 1024
DEFAULT_DISTANCE = Distance.COSINE

COLLECTIONS = {
    "schemas": "schemas",
    "sql_examples": "sql_examples",
    "knowledge": "knowledge",
    "error_codes": "error_codes",
}


class QdrantManager:
    """Qdrant 连接管理和 collection 生命周期。"""

    def __init__(self) -> None:
        settings = get_settings()
        self._client = AsyncQdrantClient(
            url=settings.qdrant_url,
            api_key=settings.qdrant_api_key or None,
            timeout=5,
            check_compatibility=False,
        )

    @property
    def client(self) -> AsyncQdrantClient:
        return self._client

    async def ensure_collections(self, dimension: int = DEFAULT_DIMENSION) -> None:
        """确保所有必要的 collection 已存在。"""
        existing = await self._client.get_collections()
        existing_names = {c.name for c in existing.collections}

        for name in COLLECTIONS.values():
            if name in existing_names:
                continue
            await self._client.create_collection(
                collection_name=name,
                vectors_config=VectorParams(size=dimension, distance=DEFAULT_DISTANCE),
            )
            logger.info("Created Qdrant collection: %s (dim=%d)", name, dimension)

    async def close(self) -> None:
        await self._client.close()


# 全局实例（生命周期由 lifespan 管理）
_qdrant_manager: QdrantManager | None = None


def get_qdrant_manager() -> QdrantManager:
    global _qdrant_manager
    if _qdrant_manager is None:
        _qdrant_manager = QdrantManager()
    return _qdrant_manager


def set_qdrant_manager(manager: QdrantManager) -> None:
    global _qdrant_manager
    _qdrant_manager = manager
