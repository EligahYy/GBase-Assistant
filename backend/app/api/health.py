"""Health check endpoint with dependency status."""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.llm.client import LiteLLMClientImpl
from app.observability import metrics

logger = logging.getLogger(__name__)
router = APIRouter()


class DependencyStatus(BaseModel):
    database: str = "unknown"
    llm_api: str = "unknown"
    default_model: str = "unknown"
    vector_db: str = "unknown"
    gbase_connections: str = "unknown"


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
    if os.getenv("TESTING"):
        return "connected"
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


async def _check_gbase_connections() -> str:
    """检查 GBase 8a 数据库连接状态（从缓存读取，不触发真实测试）。"""
    try:
        from sqlalchemy import select

        from app.database import async_session_factory
        from app.models.connection import DbConnection
    except Exception:
        return "unknown"

    try:
        async with async_session_factory() as session:
            result = await session.execute(select(DbConnection).where(DbConnection.is_active.is_(True)))
            connections = result.scalars().all()

        if not connections:
            return "no_connections"

        # 读取缓存状态
        from app.services.connection_cache import get_cached_status

        tested = 0
        ok_count = 0
        for c in connections:
            if c.driver_type == "manual":
                ok_count += 1
                tested += 1
                continue
            cached = get_cached_status(c.id)
            if cached is not None:
                tested += 1
                if cached == "ok":
                    ok_count += 1
            elif c.connection_tested:
                tested += 1
                ok_count += 1

        total = len(connections)
        if tested == 0:
            return "untested"
        if ok_count == total:
            return "connected"
        if ok_count > 0:
            return "partial"
        return "disconnected"
    except Exception as e:
        logger.warning("GBase connections health check failed: %s", e)
        return "unknown"


@router.get("/health", response_model=HealthResponse)
async def health_check(db: AsyncSession = Depends(get_db)):
    settings = get_settings()
    deps = DependencyStatus(
        database=await _check_database(db),
        llm_api=await _check_llm_api(),
        default_model=settings.default_model,
        vector_db=await _check_vector_db(),
        gbase_connections=await _check_gbase_connections(),
    )

    _STATE_TO_GAUGE = {
        "connected": 1.0,
        "ok": 1.0,
        "partial": 0.5,
        "degraded": 0.5,
        "untested": 0.5,
        "no_connections": 0.5,
        "disconnected": 0.0,
        "unreachable": 0.0,
        "unknown": 0.0,
    }
    metrics.set_dependency_up("database", _STATE_TO_GAUGE.get(deps.database, 0.0))
    metrics.set_dependency_up("llm_api", _STATE_TO_GAUGE.get(deps.llm_api, 0.0))
    metrics.set_dependency_up("vector_db", _STATE_TO_GAUGE.get(deps.vector_db, 0.0))
    metrics.set_dependency_up("gbase_connections", _STATE_TO_GAUGE.get(deps.gbase_connections, 0.0))

    overall = "ok" if deps.database == "connected" and deps.llm_api == "connected" else "degraded"
    return HealthResponse(status=overall, dependencies=deps)
