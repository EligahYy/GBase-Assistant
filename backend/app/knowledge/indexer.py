"""DocumentIndexer — 将 DocumentChunk 列表并发 embedding 并写入 Qdrant，支持进度回调。"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from collections.abc import Callable, Coroutine

from qdrant_client.models import PointStruct

from app.knowledge.chunker import DocumentChunk

logger = logging.getLogger(__name__)

COLLECTION_NAME = "knowledge"

# Progress callback signature
ProgressCallback = Callable[[str, dict], Coroutine] | None  # phase, data


class DocumentIndexer:
    """并发 embedding + Qdrant upsert，支持进度回调、取消和按 document_id 增量更新。"""

    def __init__(self, embedder=None, progress_callback: ProgressCallback = None, cancel_event: asyncio.Event | None = None):
        self._embedder = embedder
        self._progress = progress_callback
        self._cancel_event = cancel_event

    async def index(
        self,
        chunks: list[DocumentChunk],
        document_id: str = "",
        clear_existing: bool = False,
    ) -> int:
        from app.vector.client import get_qdrant_manager
        from app.vector.embedder import get_embedder

        embedder = self._embedder or get_embedder()
        qdrant = get_qdrant_manager()
        await qdrant.ensure_collections(dimension=embedder.dimension)

        if clear_existing and document_id:
            await self._delete_document_chunks(qdrant.client, document_id)

        batch_size = 10
        max_concurrent = 4
        semaphore = asyncio.Semaphore(max_concurrent)
        qdrant_client = qdrant.client
        indexed = 0
        total_chunks = len(chunks)

        if self._progress:
            await self._progress("indexing", {"indexed": 0, "total": total_chunks})

        async def embed_and_upsert(batch_idx: int, batch: list[DocumentChunk]):
            if self._cancel_event and self._cancel_event.is_set():
                return batch_idx, 0
            async with semaphore:
                texts = [c.to_embedding_text() for c in batch]
                try:
                    embeddings = await embedder.embed(texts)
                except Exception as e:
                    raise RuntimeError(
                        f"Embedding 失败 (batch {batch_idx}, {len(batch)} 条): {e}"
                    ) from e
                points = [
                    PointStruct(
                        id=int(hashlib.sha256(
                            f"{c.document_id}:{c.chapter_title}:{batch_idx}:{j}".encode()
                        ).hexdigest()[:16], 16),
                        vector=embeddings[j],
                        payload=c.to_qdrant_payload(),
                    )
                    for j, c in enumerate(batch)
                ]
                await qdrant_client.upsert(collection_name=COLLECTION_NAME, points=points)
                return batch_idx, len(batch)

        tasks = [embed_and_upsert(i, chunks[i:i + batch_size]) for i in range(0, total_chunks, batch_size)]

        for coro in asyncio.as_completed(tasks):
            if self._cancel_event and self._cancel_event.is_set():
                raise asyncio.CancelledError("索引任务已被用户取消")
            try:
                _, count = await coro
            except Exception:
                # Cancel remaining tasks on first failure
                if self._cancel_event:
                    self._cancel_event.set()
                raise
            indexed += count
            if self._progress:
                await self._progress("indexing", {"indexed": indexed, "total": total_chunks})

        return indexed

    async def _delete_document_chunks(self, client, document_id: str) -> None:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        try:
            await client.delete(
                collection_name=COLLECTION_NAME,
                points_selector=Filter(
                    must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
                ),
            )
        except Exception as e:
            logger.warning("Failed to delete chunks for document %s: %s", document_id, e)

    async def dry_run(self, chunks: list[DocumentChunk]) -> list[dict]:
        """返回分块预览，不写入 Qdrant。"""
        return [
            {"title": c.chapter_title, "size": len(c.content), "preview": c.content[:200]}
            for c in chunks
        ]
