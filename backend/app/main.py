"""FastAPI 应用入口。"""
from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.config import get_settings
from app.database import init_db

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)


def create_app() -> FastAPI:
    settings = get_settings()

    app = FastAPI(
        title="GBase 8a Agent 数据库助手",
        description="基于 AI 的 GBase 8a SQL 生成和知识问答服务",
        version="0.1.0",
        docs_url="/docs" if settings.debug else None,
        redoc_url="/redoc" if settings.debug else None,
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

    @app.on_event("startup")
    async def startup():
        logger.info("初始化数据库...")
        await init_db()
        logger.info("应用启动完成，API 文档: http://localhost:8000/docs")

    return app


app = create_app()
