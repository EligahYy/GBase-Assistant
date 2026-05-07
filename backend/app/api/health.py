"""Health check endpoint with dependency status."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.llm.client import LiteLLMClientImpl

logger = logging.getLogger(__name__)
router = APIRouter()


class DependencyStatus(BaseModel):
    database: str = "unknown"
    llm_api: str = "unknown"
    default_model: str = "unknown"
    vector_db: str = "unknown"


class HealthResponse(BaseModel):
    status: str
    version: str = "0.3.0"
    dependencies: DependencyStatus


async def _check_database(db: AsyncSession) -> str:
    try:
        await db.execute(text("SELECT 1"))
        return "connected"
    except Exception as e:
        logger.warning("Database health check failed: %s", e)
        return "disconnected"


async def _check_llm_api() -> str:
    try:
        settings = get_settings()
        client = LiteLLMClientImpl(model=settings.default_model)
        await client.complete([{"role": "user", "content": "hi"}], max_tokens=1)
        return "connected"
    except Exception as e:
        logger.warning("LLM API health check failed: %s", e)
        return "unreachable"


async def _check_vector_db() -> str:
    """检查 Qdrant 状态：connected / degraded / disconnected。"""
    try:
        from app.vector.client import get_qdrant_manager, is_qdrant_available
    except Exception as e:
        logger.debug("vector 模块加载失败: %s", e)
        return "disconnected"

    if not is_qdrant_available():
        return "disconnected"

    try:
        await get_qdrant_manager().client.get_collections()
        return "connected"
    except Exception as e:
        logger.warning("Qdrant 健康检查失败: %s", e)
        return "degraded"


@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    deps = DependencyStatus(
        database=await _check_database(db),
        llm_api=await _check_llm_api(),
        default_model=settings.default_model,
        vector_db=await _check_vector_db(),
    )
    overall = "ok" if deps.database == "connected" and deps.llm_api == "connected" else "degraded"
    return HealthResponse(status=overall, dependencies=deps)
