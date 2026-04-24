"""SQLite async 数据库引擎和 session 工厂。"""
from __future__ import annotations

from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase

from app.config import get_settings


class Base(DeclarativeBase):
    pass


def _get_engine():
    settings = get_settings()
    # 确保数据目录存在
    db_path = settings.database_url.replace("sqlite+aiosqlite:///", "")
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)

    return create_async_engine(
        settings.database_url,
        echo=settings.debug,
        connect_args={"check_same_thread": False},
    )


engine = _get_engine()

async_session_factory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    expire_on_commit=False,
    class_=AsyncSession,
)


async def get_db() -> AsyncSession:
    """FastAPI 依赖：获取数据库 session（自动关闭）"""
    async with async_session_factory() as session:
        yield session


async def init_db() -> None:
    """应用启动时创建所有表（如未存在）"""
    # 导入所有 model 确保 Base.metadata 完整
    import app.models.connection  # noqa: F401
    import app.models.conversation  # noqa: F401
    import app.models.message  # noqa: F401
    import app.models.sql_feedback  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
