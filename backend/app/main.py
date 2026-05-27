"""FastAPI 应用入口。"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import get_settings
from app.database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


async def _background_sync_all_to_qdrant(embedder) -> None:
    """后台任务：同步 JSON 知识库（FAQ/错误码/运维文档）到 Qdrant。

    Markdown 知识库通过 Admin API /api/admin/reindex-web 手动触发。
    官方文档需先运行 web_crawler 爬取到 knowledge/official/。
    """
    try:
        from app.vector.ingest import sync_all_to_qdrant

        logger.info("后台知识库同步开始（JSON: FAQ/错误码/运维文档）...")
        results = await sync_all_to_qdrant(embedder)
        logger.info("后台知识库同步完成: %s", results)
    except Exception as e:
        logger.warning("后台知识库同步失败: %s", e)


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
        try:
            from app.vector.client import get_qdrant_manager, set_qdrant_available
            from app.vector.embedder import get_embedder

            qdrant_mgr = get_qdrant_manager()
            embedder = get_embedder()
            await qdrant_mgr.ensure_collections(dimension=embedder.dimension)
            logger.info("Qdrant collections 就绪 (dim=%d)", embedder.dimension)

            # Qdrant 可用时才预热 Embedding 模型
            await embedder.embed(["warmup"])
            logger.info("Embedding 模型预热完成")

            # collections 就绪后即可标记 Qdrant 可用（请求走 Qdrant 路径，空结果由 FallbackRetriever 回退）
            set_qdrant_available(True)
            logger.info("Qdrant 向量检索已启用")

            # 知识库同步放入后台任务，不阻塞启动
            if os.getenv("SKIP_VECTOR_SYNC"):
                logger.info("SKIP_VECTOR_SYNC: 跳过知识库同步")
            else:
                asyncio.create_task(_background_sync_all_to_qdrant(embedder))
                logger.info("知识库同步已放入后台任务")
        except Exception as e:
            logger.warning("Qdrant 初始化失败，回退到文件模式: %s", e)

    # 启动连接健康检查器（后台主动探测 GBase 连接状态）
    try:
        from app.services.connection_health_checker import get_health_checker

        await get_health_checker().start()
        logger.info("ConnectionHealthChecker 已启动")
    except Exception as e:
        logger.warning("ConnectionHealthChecker 启动失败: %s", e)

    logger.info("应用启动完成，API 文档: http://localhost:8000/docs")
    yield
    logger.info("应用关闭")

    # 停止连接健康检查器
    try:
        from app.services.connection_health_checker import get_health_checker

        await get_health_checker().stop()
    except Exception:
        pass

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

    from app.api.chat_v2 import router as chat_v2_router
    app.include_router(chat_v2_router, prefix="/api")

    return app


app = create_app()
