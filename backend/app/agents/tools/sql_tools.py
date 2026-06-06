"""SQL tool implementations — ValidateSQLTool, ExecuteSQLTool.

Converted from validate_sql() in app.sql.validator and sql_executor_node in graph.py.
"""

from __future__ import annotations

import logging
from typing import Any

from app.agents.tools.base import ToolParameter

logger = logging.getLogger(__name__)


class ValidateSQLTool:
    """Tool: validate SQL syntax, GBase 8a dialect compliance, and schema cross-references."""

    def __init__(self) -> None:
        pass

    @property
    def name(self) -> str:
        return "validate_sql"

    @property
    def description(self) -> str:
        return (
            "Validate SQL syntax and GBase 8a dialect compliance. "
            "Returns whether the SQL is valid, plus any errors and warnings."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="sql",
                type="string",
                description="The SQL statement to validate",
            ),
        ]

    async def execute(self, sql: str = "", **kwargs: Any) -> Any:
        """Validate SQL syntax and GBase 8a dialect compliance.

        Args:
            sql: The SQL statement to validate.

        Returns:
            dict with keys: valid (bool), errors (list[str]), warnings (list[str]).
        """
        query = sql or kwargs.get("sql", "")
        if not query:
            return {"valid": False, "errors": ["SQL 语句为空"], "warnings": []}

        from app.sql.validator import validate_sql

        result = validate_sql(query)
        return {
            "valid": result.is_valid,
            "errors": result.errors,
            "warnings": result.warnings,
        }

    def format_result(self, result: Any) -> dict:
        """Format validation results for display.

        Args:
            result: dict from execute().

        Returns:
            {"summary": str, "detail": dict|None, "truncated": bool}
        """
        if not result:
            return {
                "summary": "SQL 验证失败（无结果）。",
                "detail": None,
                "truncated": False,
            }

        is_valid = result.get("valid", False)
        errors = result.get("errors", [])
        warnings = result.get("warnings", [])

        if is_valid:
            summary = "SQL 验证通过"
            if warnings:
                summary += f"（{len(warnings)} 个警告）"
        else:
            summary = f"SQL 验证失败（{len(errors)} 个错误）"

        return {
            "summary": summary,
            "detail": {
                "valid": is_valid,
                "errors": errors,
                "warnings": warnings,
            },
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


class ExecuteSQLTool:
    """Tool: execute a read-only SQL statement via SQLSandbox.

    Uses the same logic as sql_executor_node in graph.py.
    """

    def __init__(self, db_connection_id: str) -> None:
        self._db_connection_id = db_connection_id

    @property
    def name(self) -> str:
        return "execute_sql"

    @property
    def description(self) -> str:
        return (
            "Execute a read-only SQL statement (SELECT/SHOW/DESCRIBE) against the connected GBase 8a database. "
            "Returns columns, rows, row count, and execution time."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="sql",
                type="string",
                description="The SQL statement to execute (must be SELECT, SHOW, DESCRIBE, or EXPLAIN)",
            ),
        ]

    async def execute(self, sql: str = "", **kwargs: Any) -> Any:
        """Execute SQL via SQLSandbox in read-only mode.

        Args:
            sql: The SQL to execute.

        Returns:
            dict with keys: columns, rows, row_count, execution_time_ms, truncated,
            or {"error": str} on failure.
        """
        query = sql or kwargs.get("sql", "")
        if not query:
            return {"error": "SQL 语句为空"}

        if not self._db_connection_id:
            return {"error": "未选择数据库连接"}

        from app.api.connections import _to_connection_config
        from app.database import async_session_factory
        from app.db_connectors.connector_factory import get_connector
        from app.models.connection import DbConnection
        from app.sql.sandbox import SQLSandbox, SQLSandboxError
        from sqlalchemy import select

        try:
            async with async_session_factory() as session:
                result = await session.execute(
                    select(DbConnection).where(DbConnection.id == self._db_connection_id)
                )
                conn = result.scalar_one_or_none()
                # Extract fields while session is still open
                if not conn or conn.driver_type == "manual":
                    return {"error": "数据库连接不可用"}
                driver_type = conn.driver_type
                conn_config = _to_connection_config(conn)

            connector = get_connector(driver_type)
            if not connector:
                return {"error": f"驱动 {driver_type} 不可用"}
            sandbox = SQLSandbox()
            query_result = await sandbox.execute_readonly(
                connector, conn_config, query, max_rows=1000, timeout_seconds=30
            )

            return {
                "columns": query_result.columns,
                "rows": query_result.rows[:50],
                "row_count": query_result.row_count,
                "execution_time_ms": round(query_result.execution_time_ms, 2),
                "truncated": query_result.truncated or query_result.row_count > 50,
            }
        except SQLSandboxError as e:
            return {"error": str(e)}
        except Exception as e:
            logger.error("SQL execution failed: %s", e)
            return {"error": str(e)}

    def format_result(self, result: Any) -> dict:
        """Format SQL execution results for display.

        Args:
            result: dict from execute().

        Returns:
            {"summary": str, "detail": dict|None, "truncated": bool}
        """
        if not result:
            return {
                "summary": "SQL 执行失败（无结果）。",
                "detail": None,
                "truncated": False,
            }

        if isinstance(result, dict) and "error" in result:
            return {
                "summary": f"SQL 执行失败: {result['error']}",
                "detail": None,
                "truncated": False,
            }

        row_count = result.get("row_count", 0)
        exec_time = result.get("execution_time_ms", 0)
        truncated = result.get("truncated", False)

        summary = f"查询完成: {row_count} 行（{exec_time}ms）"
        if truncated:
            summary += "（已截断）"

        return {
            "summary": summary,
            "detail": {
                "columns": result.get("columns", []),
                "rows": result.get("rows", []),
                "row_count": row_count,
                "execution_time_ms": exec_time,
                "truncated": truncated,
            },
            "truncated": truncated,
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
