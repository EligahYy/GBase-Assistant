"""SQL proposal and execution tools."""

from __future__ import annotations

import logging
from typing import Any

from app.agents.tools.base import ToolParameter

logger = logging.getLogger(__name__)


class SubmitSQLTool:
    """Submit a candidate SQL — validates & executes atomically, returns result directly.

    Combines what were previously 3 separate graph nodes (tools → validate → execute)
    into a single atomic tool call. The agent receives the result immediately and
    can call final_answer without any intermediate routing.
    """

    def __init__(self, db_connection_id: str = "") -> None:
        self._db_connection_id = db_connection_id

    @property
    def name(self) -> str:
        return "submit_sql"

    @property
    def description(self) -> str:
        return (
            "Submit a GBase 8a SQL query for validation and execution. "
            "The tool automatically validates (read-only safety, dialect, schema) "
            "and executes the query, returning the result directly. "
            "Check the 'status' field: 'completed' means the query ran successfully, "
            "'validation_failed' means the SQL has errors (fix and retry), "
            "'execution_failed' means a runtime error occurred. "
            "Call this ONLY when you have finished schema exploration."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [ToolParameter(name="sql", type="string", description="The final read-only SQL query to execute")]

    async def execute(self, sql: str = "", **kwargs: Any) -> dict:
        """Validate and execute SQL atomically.

        Returns:
            {"status": "completed", "sql": sql, "columns": [...], "rows": [[...]],
             "row_count": N, "execution_time_ms": M, "truncated": bool}
            or {"status": "validation_failed", "sql": sql, "errors": [...], "warnings": [...]}
            or {"status": "execution_failed", "sql": sql, "error": str}
        """
        query = sql or kwargs.get("sql", "")
        if not query:
            return {"status": "validation_failed", "sql": "", "errors": ["SQL 语句为空"], "warnings": []}

        # ── Phase 1: Validate ──
        from app.sql.sandbox import SQLSandbox, SQLSandboxError
        from app.sql.validator import validate_sql

        safety_errors: list[str] = []
        try:
            SQLSandbox._validate_first_word(query)
            SQLSandbox._validate_ast(query)
            SQLSandbox._validate_single_statement(query)
        except SQLSandboxError as exc:
            safety_errors.append(str(exc))

        validation_result = validate_sql(query, schemas=None)
        all_errors = [*safety_errors, *validation_result.errors]
        all_warnings = validation_result.warnings

        if not validation_result.is_valid or safety_errors:
            return {
                "status": "validation_failed",
                "sql": query,
                "errors": all_errors,
                "warnings": all_warnings,
            }

        # ── Phase 2: Execute ──
        if not self._db_connection_id:
            return {"status": "execution_failed", "sql": query, "error": "未选择数据库连接"}

        from sqlalchemy import select

        from app.api.connections import _to_connection_config
        from app.database import async_session_factory
        from app.db_connectors.connector_factory import get_connector
        from app.models.connection import DbConnection

        try:
            async with async_session_factory() as session:
                result = await session.execute(select(DbConnection).where(DbConnection.id == self._db_connection_id))
                conn = result.scalar_one_or_none()
                if not conn or conn.driver_type == "manual":
                    return {"status": "execution_failed", "sql": query, "error": "数据库连接不可用"}
                driver_type = conn.driver_type
                conn_config = _to_connection_config(conn)

            connector = get_connector(driver_type)
            if not connector:
                return {"status": "execution_failed", "sql": query, "error": f"驱动 {driver_type} 不可用"}

            sandbox = SQLSandbox()
            query_result = await sandbox.execute_readonly(
                connector, conn_config, query, max_rows=1000, timeout_seconds=30
            )

            return {
                "status": "completed",
                "sql": query,
                "columns": query_result.columns,
                "rows": query_result.rows[:50],
                "row_count": query_result.row_count,
                "execution_time_ms": round(query_result.execution_time_ms, 2),
                "truncated": query_result.truncated or query_result.row_count > 50,
            }
        except SQLSandboxError as e:
            return {"status": "validation_failed", "sql": query, "errors": [str(e)], "warnings": all_warnings}
        except Exception as e:
            logger.error("SQL execution failed: %s", e)
            return {"status": "execution_failed", "sql": query, "error": str(e)}

    def format_result(self, result: Any) -> dict:
        """Format the atomic result for display + LLM context."""
        if not isinstance(result, dict):
            return {"summary": "SQL 执行失败（无结果）。", "detail": None, "truncated": False}

        status = result.get("status", "execution_failed")
        sql = result.get("sql", "")

        if status == "completed":
            row_count = result.get("row_count", 0)
            exec_time = result.get("execution_time_ms", 0)
            truncated = result.get("truncated", False)
            columns = result.get("columns", [])
            rows = result.get("rows", [])
            summary = (
                f"SQL 执行成功：共 {row_count} 行，耗时 {exec_time}ms"
                f"{'（已截断）' if truncated else ''}。"
                "查询结果可用于生成最终摘要。"
            )
            detail = {
                "sql": sql,
                "columns": columns,
                "rows": rows,
                "row_count": row_count,
                "execution_time_ms": exec_time,
                "truncated": truncated,
                "status": status,
            }
            return {"summary": summary, "detail": detail, "truncated": truncated}

        if status == "validation_failed":
            errors = result.get("errors", [])
            error_str = "；".join(errors) if errors else "验证失败"
            summary = f"SQL 验证失败：{error_str}\n请修正后重新调用 submit_sql。"
            detail = {"sql": sql, "errors": errors, "warnings": result.get("warnings", []), "status": status}
            return {"summary": summary, "detail": detail, "truncated": False}

        # execution_failed
        error = result.get("error", "未知错误")
        summary = f"SQL 执行失败：{error}\n请检查后重试。"
        detail = {"sql": sql, "error": error, "status": status}
        return {"summary": summary, "detail": detail, "truncated": False}

    def to_openai_schema(self) -> dict:
        props = {p.name: p.to_json_schema() for p in self.parameters}
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {"type": "object", "properties": props, "required": ["sql"]},
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

        from sqlalchemy import select

        from app.api.connections import _to_connection_config
        from app.database import async_session_factory
        from app.db_connectors.connector_factory import get_connector
        from app.models.connection import DbConnection
        from app.sql.sandbox import SQLSandbox, SQLSandboxError

        try:
            async with async_session_factory() as session:
                result = await session.execute(select(DbConnection).where(DbConnection.id == self._db_connection_id))
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
