"""GetDatabaseStatusTool — queries GBase 8a runtime status metrics.

Converted from closure _make_get_database_status_tool() in semantic_mapper.py.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from app.agents.tools.base import ToolParameter

logger = logging.getLogger(__name__)


class GetDatabaseStatusTool:
    """Tool: query database runtime status via predefined system table queries.

    Runs 4 system-level queries in parallel:
    - Connection count
    - Active queries
    - Uptime
    - Table overview (top 20 by size)
    """

    def __init__(self, db_connection_id: str) -> None:
        self._db_connection_id = db_connection_id

    @property
    def name(self) -> str:
        return "get_database_status"

    @property
    def description(self) -> str:
        return (
            "Query database runtime status: connection count, active queries, "
            "uptime, and table summary. Uses pre-defined system table queries — "
            "no SQL generation needed."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return []  # No parameters — returns all status metrics

    async def execute(self, **kwargs: Any) -> Any:
        """Run 4 predefined system queries in parallel.

        Returns:
            dict with labels as keys, each value being {"columns": ..., "rows": ..., "row_count": ...}
            or {"error": str} on failure.
        """
        import asyncio

        from app.api.connections import _to_connection_config
        from app.database import async_session_factory
        from app.db_connectors.connector_factory import get_connector
        from app.models.connection import DbConnection
        from app.sql.sandbox import SQLSandbox
        from sqlalchemy import select

        if not self._db_connection_id:
            return {"error": "未选择数据库连接"}

        async with async_session_factory() as session:
            result = await session.execute(
                select(DbConnection).where(DbConnection.id == self._db_connection_id)
            )
            conn = result.scalar_one_or_none()

        if not conn:
            return {"error": "连接不存在"}

        connector = get_connector(conn.driver_type)
        config = _to_connection_config(conn)

        queries = {
            "连接数": "SELECT COUNT(*) AS cnt FROM information_schema.PROCESSLIST",
            "活跃SQL": (
                "SELECT id, user, host, db, time, state, LEFT(info,200) AS info "
                "FROM information_schema.PROCESSLIST WHERE time > 0"
            ),
            "运行时间": (
                "SELECT DATEDIFF(NOW(), MIN(create_time)) AS running_days "
                "FROM information_schema.TABLES"
            ),
            "表概况": (
                "SELECT TABLE_NAME, TABLE_ROWS, ROUND(DATA_LENGTH/1024/1024,2) AS size_mb "
                "FROM information_schema.TABLES "
                "WHERE TABLE_SCHEMA=DATABASE() "
                "ORDER BY DATA_LENGTH DESC LIMIT 20"
            ),
        }

        async def _run_one(label: str, sql: str) -> tuple[str, dict]:
            try:
                sandbox = SQLSandbox()
                qr = await sandbox.execute_readonly(
                    connector, config, sql, max_rows=100, timeout_seconds=10
                )
                return label, {
                    "columns": qr.columns,
                    "rows": qr.rows,
                    "row_count": qr.row_count,
                }
            except Exception as e:
                return label, {"error": str(e)}

        results: dict[str, dict] = {}
        tasks = [_run_one(label, sql) for label, sql in queries.items()]
        gathered = await asyncio.gather(*tasks)
        for label, data in gathered:
            results[label] = data

        return results

    def format_result(self, result: Any) -> dict:
        """Format database status results for display.

        Args:
            result: dict from execute().

        Returns:
            {"summary": str, "detail": dict|None, "truncated": bool}
        """
        if not result:
            return {
                "summary": "数据库状态查询失败。",
                "detail": None,
                "truncated": False,
            }

        if isinstance(result, dict) and "error" in result:
            return {
                "summary": f'数据库状态查询失败: {result["error"]}',
                "detail": None,
                "truncated": False,
            }

        summary = f"数据库状态: {len(result)} 个指标"
        detail = {}
        for label, data in result.items():
            if isinstance(data, dict) and "error" in data:
                detail[label] = {"error": data["error"]}
            elif isinstance(data, dict) and data.get("rows"):
                detail[label] = {
                    "columns": data["columns"],
                    "rows": data["rows"],
                    "row_count": data["row_count"],
                }
            else:
                detail[label] = {"note": "无数据"}

        return {
            "summary": summary,
            "detail": detail,
            "truncated": False,
        }

    def to_openai_schema(self) -> dict:
        """Return OpenAI function-calling schema."""
        props = {}
        required = []
        for p in self.parameters:
            props[p.name] = p.to_json_schema()
            if p.required:
                required.append(p.name)
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": props,
                    "required": required,
                },
            },
        }
