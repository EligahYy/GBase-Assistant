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
from app.db_connectors.connector_factory import get_available_drivers, get_connector
from app.knowledge.loader import _parse_ddl_to_schemas
from app.models.connection import DbConnection
from app.protocols import ConnectionConfig
from app.schemas.connection import (
    ConnectionCreate,
    ConnectionResponse,
    ConnectionUpdate,
    QueryRequest,
    QueryResultResponse,
    SyncSchemaResponse,
    TableSchemaResponse,
    TestConnectionResponse,
)
from app.security.crypto import decrypt_password, encrypt_password
from app.sql.sandbox import SQLSandbox, SQLSandboxError

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


def _to_connection_config(conn: DbConnection) -> ConnectionConfig:
    """将 ORM 模型转换为 ConnectionConfig（密码解密）。"""
    password = decrypt_password(conn.password) or ""
    return ConnectionConfig(
        host=conn.host or "",
        port=conn.port or 5258,
        database=conn.database_name or "",
        username=conn.username or "",
        password=password,
        driver_type=conn.driver_type,
    )


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
        username=data.username,
        password=encrypt_password(data.password),
        driver_type=data.driver_type,
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

    update_data = data.model_dump(exclude_none=True)
    # 密码需要加密存储
    if "password" in update_data and update_data["password"] is not None:
        update_data["password"] = encrypt_password(update_data["password"])

    for field, value in update_data.items():
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


@router.post("/{connection_id}/test", response_model=TestConnectionResponse)
async def test_connection(connection_id: str, db: AsyncSession = Depends(get_db)):
    """测试数据库连通性。"""
    result = await db.execute(select(DbConnection).where(DbConnection.id == connection_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    if conn.driver_type == "manual":
        return TestConnectionResponse(status="ok", message="手动模式（无需连接测试）", driver="manual")

    connector = get_connector(conn.driver_type)
    if not connector:
        return TestConnectionResponse(
            status="error", message=f"驱动 {conn.driver_type} 未安装或不可用", driver=conn.driver_type
        )

    config = _to_connection_config(conn)
    ok, message = await connector.test(config)

    # 更新测试状态
    conn.connection_tested = ok
    await db.commit()

    status = "ok" if ok else "error"
    return TestConnectionResponse(status=status, message=message, driver=conn.driver_type)


@router.post("/{connection_id}/sync-schema", response_model=SyncSchemaResponse)
async def sync_schema_from_db(connection_id: str, db: AsyncSession = Depends(get_db)):
    """从生产数据库自动同步 schema。"""
    result = await db.execute(select(DbConnection).where(DbConnection.id == connection_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    if conn.driver_type == "manual":
        raise HTTPException(status_code=400, detail="手动模式不支持自动同步，请粘贴 DDL")

    connector = get_connector(conn.driver_type)
    if not connector:
        raise HTTPException(status_code=503, detail=f"驱动 {conn.driver_type} 未安装或不可用")

    config = _to_connection_config(conn)
    try:
        schemas = await connector.fetch_schema(config)
    except Exception as e:
        logger.error("Schema 同步失败: %s", e)
        raise HTTPException(status_code=502, detail=f"Schema 同步失败: {e}") from e

    # 格式化为 DDL 文本
    ddl_lines = []
    for s in schemas:
        ddl_lines.append(s.ddl)
    schema_ddl = "\n\n".join(ddl_lines)

    # 保存
    conn.schema_ddl = schema_ddl
    conn.last_synced_at = datetime.now(UTC)
    conn.connection_tested = True
    await db.commit()
    await db.refresh(conn)

    # 触发向量化
    asyncio.create_task(_trigger_schema_indexing(conn.id, conn.schema_ddl))

    return SyncSchemaResponse(tables=len(schemas), synced_at=conn.last_synced_at)


@router.post("/{connection_id}/query", response_model=QueryResultResponse)
async def execute_query(connection_id: str, body: QueryRequest, db: AsyncSession = Depends(get_db)):
    """在沙箱中执行只读 SQL 查询。"""
    result = await db.execute(select(DbConnection).where(DbConnection.id == connection_id))
    conn = result.scalar_one_or_none()
    if not conn:
        raise HTTPException(status_code=404, detail="连接不存在")

    if conn.driver_type == "manual":
        raise HTTPException(status_code=400, detail="手动模式不支持 SQL 执行")

    connector = get_connector(conn.driver_type)
    if not connector:
        raise HTTPException(status_code=503, detail=f"驱动 {conn.driver_type} 未安装或不可用")

    config = _to_connection_config(conn)
    sandbox = SQLSandbox()

    try:
        query_result = await sandbox.execute_readonly(
            connector,
            config,
            body.sql,
            max_rows=body.max_rows or 1000,
            timeout_seconds=30,
        )
    except SQLSandboxError as e:
        raise HTTPException(status_code=403, detail=str(e)) from e
    except TimeoutError as e:
        raise HTTPException(status_code=408, detail=str(e)) from e
    except Exception as e:
        logger.error("SQL 执行失败: %s", e)
        raise HTTPException(status_code=502, detail=f"SQL 执行失败: {e}") from e

    return QueryResultResponse(
        columns=query_result.columns,
        rows=query_result.rows,
        row_count=query_result.row_count,
        execution_time_ms=query_result.execution_time_ms,
        truncated=query_result.truncated,
    )


@router.get("/drivers/available")
async def available_drivers():
    """返回当前环境中可用的驱动类型列表。"""
    return {"drivers": get_available_drivers()}
