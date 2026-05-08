"""数据库性能洞察 API — 系统表查询封装。"""

from __future__ import annotations

import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_connectors.connector_factory import get_connector
from app.models.connection import DbConnection
from app.protocols import ConnectionConfig
from app.security.crypto import decrypt_password
from app.sql.sandbox import SQLSandbox, SQLSandboxError

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/insights", tags=["insights"])

# 简单内存缓存 (connection_id -> {timestamp, data})
_cache: dict[str, dict[str, Any]] = {}
CACHE_TTL = 30  # 秒


def _get_cache(key: str) -> Any | None:
    entry = _cache.get(key)
    if entry and time.time() - entry["ts"] < CACHE_TTL:
        return entry["data"]
    return None


def _set_cache(key: str, data: Any) -> None:
    _cache[key] = {"ts": time.time(), "data": data}


async def _run_system_query(
    db: AsyncSession,
    connection_id: str,
    sql: str,
    max_rows: int = 500,
) -> dict[str, Any] | None:
    """在指定连接上执行系统查询。"""
    result = await db.execute(select(DbConnection).where(DbConnection.id == connection_id))
    conn = result.scalar_one_or_none()
    if not conn or conn.driver_type == "manual":
        return None

    connector = get_connector(conn.driver_type)
    if not connector:
        return None

    password = decrypt_password(conn.password) or ""
    config = ConnectionConfig(
        host=conn.host or "",
        port=conn.port or 5258,
        database=conn.database_name or "",
        username=conn.username or "",
        password=password,
        driver_type=conn.driver_type,
    )
    sandbox = SQLSandbox()

    try:
        query_result = await sandbox.execute_readonly(
            connector,
            config,
            sql,
            max_rows=max_rows,
            timeout_seconds=15,
        )
        return {
            "columns": query_result.columns,
            "rows": query_result.rows,
            "row_count": query_result.row_count,
            "execution_time_ms": query_result.execution_time_ms,
        }
    except (SQLSandboxError, TimeoutError) as e:
        return {"error": str(e)}
    except Exception as e:
        logger.warning("Insights 查询失败: %s", e)
        return {"error": f"查询失败: {e}"}


@router.get("/connections/{connection_id}/overview")
async def get_overview(
    connection_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """获取数据库性能概览（带 30 秒缓存）。"""
    cache_key = f"overview:{connection_id}"
    cached = _get_cache(cache_key)
    if cached:
        return cached

    # 1. 表大小统计
    table_stats = await _run_system_query(
        db,
        connection_id,
        "SHOW TABLE STATUS",
        max_rows=200,
    )

    # 2. 当前进程
    processes = await _run_system_query(
        db,
        connection_id,
        "SHOW FULL PROCESSLIST",
        max_rows=100,
    )

    # 3. 状态变量
    status_vars = await _run_system_query(
        db,
        connection_id,
        "SHOW STATUS WHERE Variable_name IN ('Threads_connected', 'Threads_running', 'Uptime', 'Queries', 'Slow_queries')",
        max_rows=20,
    )

    # 4. 版本信息
    version = await _run_system_query(
        db,
        connection_id,
        "SELECT VERSION() AS version",
        max_rows=1,
    )

    overview = {
        "connection_id": connection_id,
        "timestamp": time.time(),
        "table_stats": table_stats or {"error": "无法获取表统计"},
        "processes": processes or {"error": "无法获取进程列表"},
        "status": _parse_status(status_vars),
        "version": _extract_version(version),
    }

    _set_cache(cache_key, overview)
    return overview


@router.get("/connections/{connection_id}/skew/{table_name}")
async def get_skew(
    connection_id: str,
    table_name: str,
    db: AsyncSession = Depends(get_db),
) -> dict[str, Any]:
    """检测指定表的数据分布倾斜（各节点行数差异）。"""
    cache_key = f"skew:{connection_id}:{table_name}"
    cached = _get_cache(cache_key)
    if cached:
        return cached

    # 安全检查：只允许表名包含字母数字下划线
    safe_table = "".join(c for c in table_name if c.isalnum() or c == "_")
    if not safe_table:
        raise HTTPException(status_code=400, detail="无效的表名")

    sql = f"SELECT DBNODE() AS node, COUNT(*) AS cnt FROM `{safe_table}` GROUP BY DBNODE() ORDER BY cnt DESC"
    result = await _run_system_query(db, connection_id, sql, max_rows=100)

    if result and not result.get("error"):
        skew_data = _calc_skew(result)
        _set_cache(cache_key, skew_data)
        return skew_data

    return result or {"error": "无法获取分布数据"}


def _parse_status(raw: dict[str, Any] | None) -> dict[str, Any]:
    """解析 SHOW STATUS 结果为结构化字典。"""
    if not raw or raw.get("error"):
        return {"error": raw.get("error") if raw else "查询失败"}

    status: dict[str, str | int] = {}
    for row in raw.get("rows", []):
        if len(row) >= 2:
            key = str(row[0])
            val = str(row[1])
            # 尝试转为整数
            try:
                status[key] = int(val)
            except ValueError:
                status[key] = val
    return status


def _extract_version(raw: dict[str, Any] | None) -> str | None:
    if not raw or raw.get("error"):
        return None
    rows = raw.get("rows", [])
    if rows and len(rows[0]) > 0:
        return str(rows[0][0])
    return None


def _calc_skew(result: dict[str, Any]) -> dict[str, Any]:
    """计算数据倾斜指标。"""
    rows = result.get("rows", [])
    if not rows:
        return {"nodes": [], "total": 0, "skew_ratio": 0, "max_node": None, "min_node": None}

    nodes = []
    total = 0
    max_cnt = 0
    min_cnt = float("inf")
    max_node = None
    min_node = None

    for row in rows:
        if len(row) >= 2:
            node = str(row[0])
            cnt = int(row[1]) if str(row[1]).isdigit() else 0
            nodes.append({"node": node, "count": cnt})
            total += cnt
            if cnt > max_cnt:
                max_cnt = cnt
                max_node = node
            if cnt < min_cnt:
                min_cnt = cnt
                min_node = node

    avg = total / len(nodes) if nodes else 0
    skew_ratio = round((max_cnt - min_cnt) / avg, 2) if avg > 0 else 0

    return {
        "nodes": nodes,
        "total": total,
        "node_count": len(nodes),
        "avg_per_node": round(avg, 0),
        "skew_ratio": skew_ratio,
        "max_node": max_node,
        "min_node": min_node,
        "is_balanced": skew_ratio < 1.5,
    }
