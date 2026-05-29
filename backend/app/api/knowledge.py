"""知识库管理 API — 文档 CRUD + SSE 索引进度。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Query, Request, UploadFile
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.knowledge.parsers.registry import create_default_registry
from app.knowledge.pipeline import delete_document_chunks, run_indexing_pipeline
from app.models.knowledge_document import KnowledgeDocument

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin/knowledge", tags=["knowledge"])

UPLOAD_DIR = Path(__file__).parent.parent.parent.parent / "knowledge" / "uploads"


def _verify_admin_token(request: Request) -> bool:
    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token:
        from app.config import get_settings

        return get_settings().debug
    provided = request.headers.get("X-Admin-Token", "")
    return provided == admin_token


class DocumentResponse(BaseModel):
    id: str
    filename: str
    file_type: str
    file_size: int
    status: str
    chunk_count: int
    error_message: str | None
    created_at: str
    indexed_at: str | None
    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


class IndexStateResponse(BaseModel):
    total_documents: int
    total_chunks: int
    ready_documents: int
    last_indexed_at: str | None


_parser_registry = None
_progress_queues: dict[str, list[asyncio.Queue]] = {}
_cancel_events: dict[str, asyncio.Event] = {}


def _get_parser_registry():
    global _parser_registry
    if _parser_registry is None:
        _parser_registry = create_default_registry()
    return _parser_registry


def _emit_progress(document_id: str, event: str, data: dict):
    queues = _progress_queues.get(document_id, [])
    payload = json.dumps({"event": event, "data": data}, ensure_ascii=False)
    for q in queues:
        try:
            q.put_nowait(payload)
        except asyncio.QueueFull:
            pass


@router.get("/documents", response_model=DocumentListResponse)
async def list_documents(
    request: Request,
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
    file_type: str | None = Query(None),
    status: str | None = Query(None),
    db: AsyncSession = Depends(get_db),
) -> DocumentListResponse:
    if not _verify_admin_token(request):
        raise HTTPException(status_code=403, detail="需要管理权限")

    query = select(KnowledgeDocument)
    count_query = select(func.count()).select_from(KnowledgeDocument)
    if file_type:
        query = query.where(KnowledgeDocument.file_type == file_type)
        count_query = count_query.where(KnowledgeDocument.file_type == file_type)
    if status:
        query = query.where(KnowledgeDocument.status == status)
        count_query = count_query.where(KnowledgeDocument.status == status)

    total = await db.scalar(count_query)
    rows = (
        (
            await db.execute(
                query.order_by(KnowledgeDocument.created_at.desc()).offset((page - 1) * page_size).limit(page_size)
            )
        )
        .scalars()
        .all()
    )

    return DocumentListResponse(
        documents=[
            DocumentResponse(
                id=r.id,
                filename=r.filename,
                file_type=r.file_type,
                file_size=r.file_size,
                status=r.status,
                chunk_count=r.chunk_count,
                error_message=r.error_message,
                created_at=r.created_at.isoformat() if r.created_at else "",
                indexed_at=r.indexed_at.isoformat() if r.indexed_at else None,
            )
            for r in rows
        ],
        total=total or 0,
    )


@router.post("/documents/upload")
async def upload_document(
    request: Request,
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
) -> DocumentResponse:
    if not _verify_admin_token(request):
        raise HTTPException(status_code=403, detail="需要管理权限")
    if not file.filename:
        raise HTTPException(status_code=400, detail="文件名不能为空")

    ext = file.filename.rsplit(".", 1)[-1].lower() if "." in file.filename else ""
    registry = _get_parser_registry()
    if ext not in registry.supported_formats():
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件类型: {ext}。支持: {registry.supported_formats()}",
        )

    doc_id = str(uuid.uuid4())
    doc_dir = UPLOAD_DIR / doc_id
    doc_dir.mkdir(parents=True, exist_ok=True)
    storage_path = doc_dir / file.filename

    content = await file.read()
    file_size = len(content)
    storage_path.write_bytes(content)

    doc = KnowledgeDocument(
        id=doc_id,
        filename=file.filename,
        file_type=ext,
        file_size=file_size,
        storage_path=str(storage_path),
        status="pending",
    )
    db.add(doc)
    await db.commit()
    await db.refresh(doc)

    asyncio.create_task(_index_document(doc_id, str(storage_path), ext))
    return DocumentResponse(
        id=doc.id,
        filename=doc.filename,
        file_type=doc.file_type,
        file_size=doc.file_size,
        status=doc.status,
        chunk_count=doc.chunk_count,
        error_message=doc.error_message,
        created_at=doc.created_at.isoformat() if doc.created_at else "",
        indexed_at=None,
    )


async def _index_document(doc_id: str, file_path: str, file_type: str):
    from app.database import async_session_factory

    # 创建取消事件
    cancel_event = asyncio.Event()
    _cancel_events[doc_id] = cancel_event

    async with async_session_factory() as db:
        doc = await db.get(KnowledgeDocument, doc_id)
        if not doc:
            _cancel_events.pop(doc_id, None)
            return
        registry = _get_parser_registry()

        async def update_status(status: str):
            try:
                doc.status = status
                await db.commit()
            except Exception:
                pass
            _emit_progress(doc_id, "progress", {"phase": status})

        async def progress_fn(phase: str, data: dict):
            _emit_progress(doc_id, "progress", {"phase": phase, **data})

        try:
            # 预检查：验证 Qdrant 和 embedding 可用
            from app.vector.client import is_qdrant_available
            from app.vector.embedder import get_embedder
            if not is_qdrant_available():
                raise RuntimeError("Qdrant 服务未连接，请确认 Qdrant 已启动 (localhost:6333)")
            try:
                embedder = get_embedder()
                logger.info("Embedder ready: dim=%d", embedder.dimension)
            except Exception as e:
                raise RuntimeError(f"Embedding 模型加载失败 — 请检查 models.yaml 中 embedding 配置及对应的 API Key: {e}")

            count = await run_indexing_pipeline(
                document_id=doc_id,
                file_path=Path(file_path),
                file_type=file_type,
                parser_registry=registry,
                status_callback=update_status,
                progress_callback=progress_fn,
                cancel_event=cancel_event,
            )
            doc.status = "ready"
            doc.chunk_count = count
            doc.indexed_at = datetime.now(UTC)
            await db.commit()
            _emit_progress(doc_id, "complete", {"chunk_count": count, "phase": "ready"})
        except asyncio.CancelledError:
            doc.status = "error"
            doc.error_message = "用户取消了索引任务"
            await db.commit()
            _emit_progress(doc_id, "error", {"message": "索引已被取消", "phase": "error"})
        except Exception as e:
            logger.error("Index failed for document %s: %s", doc_id, e)
            err_msg = str(e).replace("\n", " ").replace('"', "'")
            if len(err_msg) > 300:
                err_msg = err_msg[:300] + "..."
            doc.status = "error"
            doc.error_message = err_msg
            await db.commit()
            _emit_progress(doc_id, "error", {"message": err_msg, "phase": "error"})
        finally:
            _cancel_events.pop(doc_id, None)


@router.get("/documents/{document_id}/index-progress")
async def index_progress(request: Request, document_id: str) -> StreamingResponse:
    if not _verify_admin_token(request):
        raise HTTPException(status_code=403, detail="需要管理权限")
    q: asyncio.Queue = asyncio.Queue(maxsize=50)
    _progress_queues.setdefault(document_id, []).append(q)

    async def event_stream():
        try:
            while True:
                try:
                    payload = await asyncio.wait_for(q.get(), timeout=30)
                    yield f"data: {payload}\n\n"
                except TimeoutError:
                    yield 'data: {"event": "heartbeat"}\n\n'
        except asyncio.CancelledError:
            pass
        finally:
            try:
                _progress_queues.get(document_id, []).remove(q)
            except ValueError:
                pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.delete("/documents/{document_id}")
async def delete_document(
    request: Request,
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not _verify_admin_token(request):
        raise HTTPException(status_code=403, detail="需要管理权限")
    doc = await db.get(KnowledgeDocument, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    await delete_document_chunks(document_id)
    import shutil

    file_dir = Path(doc.storage_path).parent
    if file_dir.exists():
        shutil.rmtree(file_dir)
    await db.delete(doc)
    await db.commit()
    return {"status": "deleted"}


@router.post("/documents/{document_id}/reindex")
async def reindex_document(
    request: Request,
    document_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    if not _verify_admin_token(request):
        raise HTTPException(status_code=403, detail="需要管理权限")
    doc = await db.get(KnowledgeDocument, document_id)
    if not doc:
        raise HTTPException(status_code=404, detail="文档不存在")
    if not Path(doc.storage_path).exists():
        raise HTTPException(status_code=404, detail="文件不存在")
    doc.status = "pending"
    doc.error_message = None
    await db.commit()
    asyncio.create_task(_index_document(document_id, doc.storage_path, doc.file_type))
    return {"status": "reindexing", "document_id": document_id}


@router.get("/index-state", response_model=IndexStateResponse)
async def index_state(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> IndexStateResponse:
    if not _verify_admin_token(request):
        raise HTTPException(status_code=403, detail="需要管理权限")
    total = await db.scalar(select(func.count()).select_from(KnowledgeDocument))
    ready = await db.scalar(
        select(func.count()).select_from(KnowledgeDocument).where(KnowledgeDocument.status == "ready")
    )
    total_chunks = await db.scalar(select(func.sum(KnowledgeDocument.chunk_count)).select_from(KnowledgeDocument))
    last = await db.scalar(select(KnowledgeDocument.indexed_at).order_by(KnowledgeDocument.indexed_at.desc()).limit(1))
    return IndexStateResponse(
        total_documents=total or 0,
        total_chunks=total_chunks or 0,
        ready_documents=ready or 0,
        last_indexed_at=last.isoformat() if last else None,
    )


@router.post("/documents/{document_id}/cancel")
async def cancel_indexing(request: Request, document_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """取消正在进行的索引任务。"""
    if not _verify_admin_token(request):
        raise HTTPException(status_code=403, detail="需要管理权限")
    event = _cancel_events.get(document_id)
    if event:
        event.set()
        doc = await db.get(KnowledgeDocument, document_id)
        if doc and doc.status in ("pending", "parsing", "chunking", "indexing"):
            doc.status = "error"
            doc.error_message = "用户取消了索引任务"
            await db.commit()
        return {"status": "cancelled", "document_id": document_id}
    raise HTTPException(status_code=404, detail="未找到正在进行的索引任务")

@router.post("/reindex-all")
async def reindex_all(request: Request) -> dict:
    if not _verify_admin_token(request):
        raise HTTPException(status_code=403, detail="需要管理权限")
    from app.database import async_session_factory

    async with async_session_factory() as db:
        docs = (await db.execute(select(KnowledgeDocument))).scalars().all()
        for d in docs:
            d.status = "pending"
            d.error_message = None
        await db.commit()
        count = 0
        for d in docs:
            if Path(d.storage_path).exists():
                asyncio.create_task(_index_document(d.id, d.storage_path, d.file_type))
                count += 1
    return {"status": "reindexing", "documents": count}
