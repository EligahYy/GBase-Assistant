"""数据库连接管理 API。"""
from __future__ import annotations

import uuid
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.connection import DbConnection
from app.schemas.connection import ConnectionCreate, ConnectionResponse, ConnectionUpdate

router = APIRouter(prefix="/connections", tags=["connections"])


@router.get("", response_model=list[ConnectionResponse])
async def list_connections(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DbConnection).where(DbConnection.is_active.is_(True)).order_by(DbConnection.created_at.desc()))
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
    conn.updated_at = datetime.utcnow()
    await db.commit()
    await db.refresh(conn)
    return ConnectionResponse.from_orm_model(conn)


@router.delete("/{connection_id}", status_code=204)
async def delete_connection(connection_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(DbConnection).where(DbConnection.id == connection_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")
    conn.is_active = False
    await db.commit()
