"""SQL 执行沙箱：三层安全验证（首词预检 → AST解析 → 多语句检测）+ 超时 + 行数限制。

安全规则：
- Layer 1: 首词白名单快速拦截
- Layer 2: sqlglot AST 解析，验证语句类型，AST 遍历检查禁止关键词
- Layer 3: 多语句检测（注释剥离 + 分号检查）
- 超时：asyncio.wait_for 包装
- 行数限制：最多返回 max_rows 行
"""

from __future__ import annotations

import asyncio
import logging
import re
from typing import TYPE_CHECKING

import sqlglot
from sqlglot import exp

from app.observability import metrics

if TYPE_CHECKING:
    from app.protocols import ConnectionConfig, DatabaseConnector, QueryResult

logger = logging.getLogger(__name__)

_READ_ONLY_BLOCKED: set[str] = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
    "TRUNCATE", "CREATE", "GRANT", "REVOKE",
    "MERGE", "REPLACE", "RENAME", "LOAD", "SET",
}

_READ_ONLY_ALLOWED = {"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "WITH"}

# Keywords that are dangerous even inside subqueries
_BLOCKED_AST_KEYWORDS = {
    "INSERT", "UPDATE", "DELETE", "DROP", "ALTER",
    "TRUNCATE", "CREATE", "GRANT", "REVOKE", "MERGE", "REPLACE",
}


class SQLSandboxError(Exception):
    """沙箱安全拦截。"""


class SQLSandbox:
    """SQL 执行沙箱 — 三层验证 + 超时 + 行数限制。"""

    @staticmethod
    def _validate_readonly(sql: str) -> None:
        """Layer 1: Fast string-level first-word whitelist check (backward-compat alias)."""
        SQLSandbox._validate_first_word(sql)

    @staticmethod
    def _validate_first_word(sql: str) -> None:
        """Layer 1: Fast string-level first-word whitelist check."""
        stripped = sql.strip().upper()
        first_word = stripped.split()[0] if stripped.split() else ""
        if first_word in _READ_ONLY_BLOCKED:
            raise SQLSandboxError(f"禁止执行 {first_word} 语句（沙箱只读模式）")
        if first_word not in _READ_ONLY_ALLOWED:
            raise SQLSandboxError(
                f"不允许的 SQL 类型: {first_word}（仅允许 SELECT/SHOW/DESCRIBE/EXPLAIN/WITH）"
            )

    @staticmethod
    def _validate_single_statement(sql: str) -> None:
        """Layer 3: Detect multi-statement SQL.

        Strips SQL comments (-- ... and /* ... */) and checks for semicolons
        that separate multiple statements. A trailing semicolon is allowed.
        """
        # Strip single-line comments
        no_comments = re.sub(r'--[^\n]*', '', sql)
        # Strip block comments
        no_comments = re.sub(r'/\*.*?\*/', '', no_comments, flags=re.DOTALL)
        # Strip the trailing semicolon if present
        stripped = no_comments.strip()
        if stripped.endswith(';'):
            stripped = stripped[:-1].strip()
        # Check for remaining semicolons inside the statement
        if ';' in stripped:
            raise SQLSandboxError("禁止执行多条 SQL 语句（检测到分号分隔）")

    @staticmethod
    def _validate_ast(sql: str) -> None:
        """Layer 2: Parse SQL with sqlglot, validate statement type, walk AST for blocked keywords."""
        try:
            statements = sqlglot.parse(sql, dialect="mysql")
        except Exception as e:
            raise SQLSandboxError(f"SQL 语法解析失败: {e}") from e

        if not statements or statements[0] is None:
            raise SQLSandboxError("SQL 解析失败：语句为空或无法识别")

        # Only the first statement is relevant (multi-statement already blocked by Layer 3)
        stmt = statements[0]

        # Check statement type
        stmt_type = type(stmt).__name__.upper()
        if any(kw in stmt_type for kw in ["INSERT", "UPDATE", "DELETE", "DROP", "ALTER", "TRUNCATE", "CREATE", "GRANT", "REVOKE", "MERGE", "REPLACE"]):
            raise SQLSandboxError(f"禁止执行 {stmt_type} 语句（沙箱只读模式）")

        # Walk AST for blocked keywords in subclauses
        for node in stmt.walk():
            node_type = type(node).__name__.upper()
            for kw in _BLOCKED_AST_KEYWORDS:
                if kw in node_type:
                    raise SQLSandboxError(f"SQL 中包含禁止的操作: {kw}")

    async def execute_readonly(
        self,
        connector: DatabaseConnector,
        config: ConnectionConfig,
        sql: str,
        max_rows: int = 1000,
        timeout_seconds: int = 30,
    ) -> QueryResult:
        """在安全沙箱中执行只读 SQL。

        三层安全验证：
        1. 首词白名单快速拦截
        2. sqlglot AST 解析 → 语句类型 + 关键词遍历
        3. 多语句检测（注释剥离 + 分号检查）

        Args:
            connector: 数据库连接器实例
            config: 连接配置
            sql: 要执行的 SQL（必须是单条 SELECT/SHOW/DESCRIBE）
            max_rows: 最大返回行数
            timeout_seconds: 执行超时秒数

        Returns:
            QueryResult 结构化结果

        Raises:
            SQLSandboxError: 安全规则拦截
            TimeoutError: 执行超时
        """
        # Layer 1: Fast first-word check
        try:
            self._validate_first_word(sql)
        except SQLSandboxError:
            metrics.record_sql_execution(status="blocked", latency_seconds=0.0)
            raise

        # Layer 2: AST validation
        try:
            self._validate_ast(sql)
        except SQLSandboxError:
            metrics.record_sql_execution(status="blocked", latency_seconds=0.0)
            raise

        # Layer 3: Multi-statement detection
        try:
            self._validate_single_statement(sql)
        except SQLSandboxError:
            metrics.record_sql_execution(status="blocked", latency_seconds=0.0)
            raise

        # Execute with timeout + metrics
        with metrics.time_sql_execution() as ctx:
            try:
                result = await asyncio.wait_for(
                    connector.execute(config, sql, max_rows=max_rows, timeout=timeout_seconds),
                    timeout=timeout_seconds + 5,
                )
            except TimeoutError:
                ctx["status"] = "timeout"
                raise TimeoutError(f"SQL 执行超时（>{timeout_seconds}秒）") from None
            except Exception:
                ctx["status"] = "error"
                raise
            ctx["status"] = "ok"

        return result
