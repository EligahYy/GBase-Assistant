"""SQL 执行沙箱：只读、超时、行数限制。

安全规则：
- 只读拦截：首词白名单检测 SELECT/SHOW/DESCRIBE/EXPLAIN/WITH
- 超时：asyncio.wait_for 包装
- 行数限制：最多返回 max_rows 行
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

from app.observability import metrics

if TYPE_CHECKING:
    from app.protocols import ConnectionConfig, DatabaseConnector, QueryResult

logger = logging.getLogger(__name__)

_READ_ONLY_BLOCKED: set[str] = {
    "INSERT",
    "UPDATE",
    "DELETE",
    "DROP",
    "ALTER",
    "TRUNCATE",
    "CREATE",
    "GRANT",
    "REVOKE",
    "MERGE",
    "REPLACE",
}

_READ_ONLY_ALLOWED = {"SELECT", "SHOW", "DESCRIBE", "DESC", "EXPLAIN", "WITH"}


class SQLSandboxError(Exception):
    """沙箱安全拦截。"""


class SQLSandbox:
    """SQL 执行沙箱 — 首词白名单 + 超时 + 行数限制。"""

    @staticmethod
    def _validate_readonly(sql: str) -> None:
        """验证 SQL 首词为允许的只读类型。"""
        stripped = sql.strip().upper()
        first_word = stripped.split()[0] if stripped.split() else ""
        if first_word in _READ_ONLY_BLOCKED:
            raise SQLSandboxError(f"禁止执行 {first_word} 语句（沙箱只读模式）")
        if first_word not in _READ_ONLY_ALLOWED:
            raise SQLSandboxError(f"不允许的 SQL 类型: {first_word}（仅允许 SELECT/SHOW/DESCRIBE/EXPLAIN/WITH）")

    async def execute_readonly(
        self,
        connector: DatabaseConnector,
        config: ConnectionConfig,
        sql: str,
        max_rows: int = 1000,
        timeout_seconds: int = 30,
    ) -> QueryResult:
        """在安全沙箱中执行只读 SQL。

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
        # 1. 安全验证
        try:
            self._validate_readonly(sql)
        except SQLSandboxError:
            metrics.record_sql_execution(status="blocked", latency_seconds=0.0)
            raise

        # 2. 执行（带超时 + 埋点）
        with metrics.time_sql_execution() as ctx:
            try:
                result = await asyncio.wait_for(
                    connector.execute(config, sql, max_rows=max_rows, timeout=timeout_seconds),
                    timeout=timeout_seconds + 5,  # 额外 5 秒缓冲
                )
            except TimeoutError:
                ctx["status"] = "timeout"
                raise TimeoutError(f"SQL 执行超时（>{timeout_seconds}秒）") from None
            except Exception:
                ctx["status"] = "error"
                raise
            ctx["status"] = "ok"

        return result
