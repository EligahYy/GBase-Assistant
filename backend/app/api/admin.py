"""管理接口：Reindex 等运维操作。"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/admin", tags=["admin"])


class ReindexResponse(BaseModel):
    status: str
    results: dict[str, int]


class ReindexRequest(BaseModel):
    force: bool = True


def _verify_admin_token(request: Request) -> bool:
    """权限校验：X-Admin-Token 请求头需匹配环境变量 ADMIN_TOKEN；
    未配置 ADMIN_TOKEN 时，debug 模式自动放行。"""
    admin_token = os.getenv("ADMIN_TOKEN", "")
    if not admin_token:
        return get_settings().debug
    provided = request.headers.get("X-Admin-Token", "")
    return provided == admin_token


@router.post("/reindex", response_model=ReindexResponse)
async def reindex(request: Request, body: ReindexRequest | None = None) -> ReindexResponse:
    """强制全量重建 Qdrant 向量索引（FAQ / SQL 示例 / 错误码）。
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
