"""Knowledge Pipeline — 编排 Parser → Chunker → Indexer 全流程，更新文档状态。"""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from app.knowledge.chunker import ChunkConfig, SemanticChunker
from app.knowledge.indexer import DocumentIndexer
from app.knowledge.parsers.registry import ParserRegistry

logger = logging.getLogger(__name__)


async def run_indexing_pipeline(
    document_id: str,
    file_path: Path,
    file_type: str,
    parser_registry: ParserRegistry,
    status_callback=None,
    progress_callback=None,
    cancel_event: asyncio.Event | None = None,
) -> int:
    """执行完整的索引管道：Parse → Chunk → Index。"""
    parser = parser_registry.get(file_type)
    if not parser:
        raise ValueError(f"Unsupported file type: {file_type}")

    # Phase 1: Parse
    await _update_status(status_callback, "parsing")
    logger.info("Parsing document %s (%s)", document_id, file_type)
    parsed = await parser.parse(file_path)
    if not parsed.sections:
        raise ValueError("Document produced no sections — may be empty or unreadable")
    if cancel_event and cancel_event.is_set():
        raise asyncio.CancelledError("索引任务已被取消")

    # Phase 2: Chunk
    await _update_status(status_callback, "chunking")
    logger.info("Chunking document %s: %d sections", document_id, len(parsed.sections))
    chunker = SemanticChunker(ChunkConfig())
    chunks = await asyncio.to_thread(
        chunker.chunk, parsed, source_file=file_path.name, document_id=document_id
    )
    logger.info("Produced %d chunks for document %s", len(chunks), document_id)
    if cancel_event and cancel_event.is_set():
        raise asyncio.CancelledError("索引任务已被取消")

    # Phase 3: Index
    await _update_status(status_callback, "indexing")
    indexer = DocumentIndexer(progress_callback=progress_callback, cancel_event=cancel_event)
    count = await indexer.index(chunks, document_id=document_id, clear_existing=True)

    await _update_status(status_callback, "ready")
    return count


async def delete_document_chunks(document_id: str) -> None:
    """从 Qdrant 删除指定文档的所有 chunks。"""
    from app.vector.client import get_qdrant_manager

    qdrant = get_qdrant_manager()
    from qdrant_client.models import FieldCondition, Filter, MatchValue

    try:
        await qdrant.client.delete(
            collection_name="knowledge",
            points_selector=Filter(
                must=[FieldCondition(key="document_id", match=MatchValue(value=document_id))]
            ),
        )
        logger.info("Deleted chunks for document %s", document_id)
    except Exception as e:
        logger.warning("Failed to delete chunks for document %s: %s", document_id, e)


async def _update_status(callback, status: str):
    if callback:
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(status)
            else:
                callback(status)
        except Exception:
            pass
