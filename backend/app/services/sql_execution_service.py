"""聊天链路中的 SQL 只读执行服务。"""

from __future__ import annotations

import logging
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db_connectors.connector_factory import get_connector
from app.models.connection import DbConnection
from app.protocols import ConnectionConfig
from app.security.crypto import decrypt_password
from app.sql.sandbox import SQLSandbox, SQLSandboxError

logger = logging.getLogger(__name__)

QueryResultPayload = dict[str, Any]


async def execute_sql_for_connection(
    db: AsyncSession,
    db_connection_id: str,
    sql: str,
    max_rows: int = 100,
) -> QueryResultPayload | None:
    """对真实连接执行只读 SQL，返回可 JSON 序列化的结果。"""
    result = await db.execute(select(DbConnection).where(DbConnection.id == db_connection_id))
    conn = result.scalar_one_or_none()
    if not conn or conn.driver_type == "manual":
        return None

    connector = get_connector(conn.driver_type)
    if not connector:
        return None

    config = ConnectionConfig(
        host=conn.host or "",
        port=conn.port or 5258,
        database=conn.database_name or "",
        username=conn.username or "",
        password=decrypt_password(conn.password) or "",
        driver_type=conn.driver_type,
    )

    try:
        query_result = await SQLSandbox().execute_readonly(
            connector,
            config,
            sql,
            max_rows=max_rows,
            timeout_seconds=30,
        )
        return {
            "columns": query_result.columns,
            "rows": query_result.rows,
            "row_count": query_result.row_count,
            "execution_time_ms": query_result.execution_time_ms,
            "truncated": query_result.truncated,
        }
    except SQLSandboxError as e:
        return {"error": str(e)}
    except TimeoutError as e:
        return {"error": str(e)}
    except Exception as e:
        logger.warning("Chat SQL 执行失败: %s", e)
        return {"error": f"执行失败: {e}"}


def format_query_result_summary(query_result: QueryResultPayload) -> str:
    """生成追加到聊天内容中的查询结果摘要。"""
    result_summary = f"\n\n📊 查询结果：{query_result['row_count']} 行"
    if query_result.get("truncated"):
        result_summary += "（已截断，最多展示 100 行）"
    result_summary += f" | 耗时 {query_result['execution_time_ms']}ms"
    return result_summary
