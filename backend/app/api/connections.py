"""数据库连接管理 API。"""

from __future__ import annotations

import asyncio
import logging
import uuid
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.knowledge.loader import _parse_ddl_to_schemas
from app.models.connection import DbConnection
from app.schemas.connection import ConnectionCreate, ConnectionResponse, ConnectionUpdate, TableSchemaResponse

router = APIRouter(prefix="/connections", tags=["connections"])
logger = logging.getLogger(__name__)


async def _trigger_schema_indexing(db_id: str, schema_ddl: str | None) -> None:
    """后台任务：将 schema DDL 解析并向量化入库到 Qdrant。"""
    if not schema_ddl:
        return
    try:
        from app.vector.client import get_qdrant_manager
        from app.vector.embedder import get_embedder
        from app.vector.ingest import ingest_schemas

        embedder = get_embedder()
        schemas = _parse_ddl_to_schemas(schema_ddl)
        schema_dicts = [
            {
                "table_name": s.table_name,
                "ddl": s.ddl,
                "columns": s.columns,
                "description": s.description,
            }
            for s in schemas
        ]
        # 如果没有解析出表，将整个 DDL 作为一条记录入库
        if not schema_dicts and schema_ddl.strip():
            schema_dicts = [
                {
                    "table_name": "__all__",
                    "ddl": schema_ddl,
                    "columns": [],
                    "description": "",
                }
            ]

        await get_qdrant_manager().ensure_collections(dimension=embedder.dimension)
        count = await ingest_schemas(embedder, db_id, schema_dicts)
        logger.info("Schema 后台索引完成: db_id=%s, %d 个表", db_id, count)
    except Exception as e:
        logger.warning("Schema 后台索引失败（非阻塞）: db_id=%s, %s", db_id, e)


@router.get("", response_model=list[ConnectionResponse])
async def list_connections(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(DbConnection).where(DbConnection.is_active.is_(True)).order_by(DbConnection.created_at.desc())
    )
    connections = result.scalars().all()
    return [ConnectionResponse.from_orm_model(c) for c in connections]


@router.post("", response_model=ConnectionResponse, status_code=201)
async def create_connection(data: ConnectionCreate, db: AsyncSession = Depends(get_db)):
    conn = DbConnection(
        id=str(uuid.uuid4()),
        name=data.name,
        host=data.host,
        port=data.port,
        database_name=data.database_name,
        description=data.description,
        schema_ddl=data.schema_ddl,
    )
    db.add(conn)
    await db.commit()
    await db.refresh(conn)
    # 后台异步触发 schema 向量化（不阻塞响应）
    asyncio.create_task(_trigger_schema_indexing(conn.id, conn.schema_ddl))
    return ConnectionResponse.from_orm_model(conn)


@router.get("/{connection_id}", response_model=ConnectionResponse)
async def get_connection(connection_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DbConnection).where(DbConnection.id == connection_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")
    return ConnectionResponse.from_orm_model(conn)


@router.patch("/{connection_id}", response_model=ConnectionResponse)
async def update_connection(connection_id: str, data: ConnectionUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DbConnection).where(DbConnection.id == connection_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    for field, value in data.model_dump(exclude_none=True).items():
        setattr(conn, field, value)
    conn.updated_at = datetime.now(UTC)
    await db.commit()
    await db.refresh(conn)
    # 如果 schema_ddl 被更新，后台异步重新索引
    if data.schema_ddl is not None:
        asyncio.create_task(_trigger_schema_indexing(conn.id, conn.schema_ddl))
    return ConnectionResponse.from_orm_model(conn)


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(connection_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DbConnection).where(DbConnection.id == connection_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")
    conn.is_active = False
    await db.commit()


@router.get("/{connection_id}/schema/tables", response_model=list[TableSchemaResponse])
async def list_schema_tables(connection_id: str, db: AsyncSession = Depends(get_db)):
    """解析连接的 schema_ddl，返回结构化表列表。"""
    result = await db.execute(select(DbConnection).where(DbConnection.id == connection_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")
    if not conn.schema_ddl:
        return []

    schemas = _parse_ddl_to_schemas(conn.schema_ddl)
    return [
        TableSchemaResponse(
            table_name=s.table_name,
            columns=s.columns,
            ddl=s.ddl,
            description=s.description or "",
        )
        for s in schemas
    ]
