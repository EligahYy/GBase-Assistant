"""管理接口：Reindex 等运维操作。"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.sql_feedback import SQLFeedback

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


class ReindexResponse(BaseModel):
    status: str
    results: dict[str, int]


class ReindexRequest(BaseModel):
    force: bool = True


def _verify_admin_token(request: Request) -> bool:
    """权限校验：X-Admin-Token 请求头需匹配环境变量 ADMIN_TOKEN；
    未配置时默认为 123456。"""
    admin_token = os.getenv("ADMIN_TOKEN", "123456")
    provided = request.headers.get("X-Admin-Token", "")
    return provided == admin_token


@router.post("/reindex", response_model=ReindexResponse)
async def reindex(request: Request, body: ReindexRequest | None = None) -> ReindexResponse:
    """强制全量重建 Qdrant 向量索引（FAQ / Schema / 错误码）。
    需要 X-Admin-Token 请求头或 debug 模式。"""
    if not _verify_admin_token(request):
        raise HTTPException(status_code=403, detail="需要管理权限")

    from app.vector.client import is_qdrant_available
    from app.vector.embedder import get_embedder
    from app.vector.ingest import sync_all_to_qdrant

    if not is_qdrant_available():
        raise HTTPException(status_code=503, detail="Qdrant 不可用，无法重建索引")

    try:
        embedder = get_embedder()
        force = body.force if body else True
        results = await sync_all_to_qdrant(embedder, force=force)
        logger.info("管理端强制重建索引完成: %s", results)
        return ReindexResponse(status="ok", results=results)
    except Exception as e:
        logger.error("重建索引失败: %s", e)
        raise HTTPException(status_code=500, detail=f"重建索引失败: {e}") from e


class ReindexWebResponse(BaseModel):
    status: str
    chunks: int
    message: str


@router.post("/reindex-web", response_model=ReindexWebResponse)
async def reindex_web(request: Request) -> ReindexWebResponse:
    """从 gbase.cn 在线文档重建知识库索引。
    需要先运行 web_crawler 爬取页面到 knowledge/official/。
    """
    if not _verify_admin_token(request):
        raise HTTPException(status_code=403, detail="需要管理权限")

    from app.knowledge.document_chunker import build_knowledge_from_md_dir
    from app.vector.client import is_qdrant_available

    if not is_qdrant_available():
        raise HTTPException(status_code=503, detail="Qdrant 不可用")

    try:
        count = await build_knowledge_from_md_dir()
        return ReindexWebResponse(
            status="ok",
            chunks=count,
            message=f"已从本地 MD 文件索引 {count} 个章节",
        )
    except FileNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except Exception as e:
        logger.error("Web 索引失败: %s", e)
        raise HTTPException(status_code=500, detail=f"索引失败: {e}") from e


class ReindexPDFResponse(BaseModel):
    status: str
    chunks: int
    message: str


@router.post("/reindex-pdf", response_model=ReindexPDFResponse)
async def reindex_pdf(request: Request) -> ReindexPDFResponse:
    """从 PDF 产品手册重建知识库索引（后台异步执行）。

    立即返回，索引在后台运行。通过日志观察进度。
    """
    if not _verify_admin_token(request):
        raise HTTPException(status_code=403, detail="需要管理权限")

    from app.vector.client import is_qdrant_available

    if not is_qdrant_available():
        raise HTTPException(status_code=503, detail="Qdrant 不可用")

    import asyncio

    from app.knowledge.document_chunker import build_knowledge_from_pdf

    async def _run():
        try:
            count = await build_knowledge_from_pdf()
            logger.info("PDF reindex 完成: %d chunks", count)
        except Exception as e:
            logger.error("PDF reindex 失败: %s", e)

    asyncio.create_task(_run())
    logger.info("PDF reindex 已放入后台任务")
    return ReindexPDFResponse(
        status="running",
        chunks=0,
        message="索引任务已启动，正在后台执行。请观察后端日志查看进度。",
    )


@router.get("/feedback-stats")
async def feedback_stats(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> dict[str, int]:
    """SQL 反馈统计。"""
    if not _verify_admin_token(request):
        raise HTTPException(status_code=403, detail="需要管理权限")

    total = await db.scalar(select(func.count()).select_from(SQLFeedback))
    accepted = await db.scalar(select(func.count()).where(SQLFeedback.action == "accepted"))
    rejected = await db.scalar(select(func.count()).where(SQLFeedback.action == "rejected"))
    modified = await db.scalar(select(func.count()).where(SQLFeedback.action == "modified"))
    return {
        "total": total or 0,
        "accepted": accepted or 0,
        "rejected": rejected or 0,
        "modified": modified or 0,
    }
