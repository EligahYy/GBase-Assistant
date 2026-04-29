"""FastAPI 应用入口。"""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import get_settings
from app.database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """应用生命周期管理（替代已废弃的 on_event）。"""
    import os

    logger.info("初始化数据库...")
    await init_db()

    # Phase 3: 初始化 Qdrant collections 和 embedding 模型
    # 测试环境通过 TESTING=1 跳过，避免下载大模型或等待网络超时
    if os.getenv("TESTING"):
        logger.info("测试模式：跳过 Qdrant 和 Embedding 初始化")
    else:
        # Qdrant 初始化和知识库同步
        try:
            from app.vector.client import get_qdrant_manager, set_qdrant_available
            from app.vector.embedder import get_embedder
            from app.vector.ingest import sync_all_to_qdrant

            qdrant_mgr = get_qdrant_manager()
            embedder = get_embedder()
            await qdrant_mgr.ensure_collections(dimension=embedder.dimension)
            set_qdrant_available(True)
            logger.info("Qdrant collections 就绪 (dim=%d)", embedder.dimension)

            # Qdrant 可用时才预热 Embedding 模型
            await embedder.embed(["warmup"])
            logger.info("Embedding 模型预热完成")

            # 同步知识库到 Qdrant（增量）
            await sync_all_to_qdrant(embedder)
        except Exception as e:
            logger.warning("Qdrant 初始化失败，回退到文件模式: %s", e)

    logger.info("应用启动完成，API 文档: http://localhost:8000/docs")
    yield
    logger.info("应用关闭")
    try:
        from app.vector.client import get_qdrant_manager

        await get_qdrant_manager().close()
    except Exception:
        pass


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="GBase 8a Agent 数据库助手",
        description="基于 AI 的 GBase 8a SQL 生成和知识问答服务",
        version="0.1.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Conversation-Id"],  # 允许前端读取流式响应中的对话 ID
    )

    app.include_router(api_router)

    return app


app = create_app()
