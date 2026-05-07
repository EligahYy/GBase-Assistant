"""SQL 执行沙箱：只读、超时、行数限制。

安全规则：
- 只读拦截：AST 级别检测 INSERT/UPDATE/DELETE/DROP/ALTER/CREATE/TRUNCATE/GRANT/REVOKE
- 多语句拦截：; 分隔的多条 SQL 拒绝执行
- 超时：asyncio.wait_for 包装
- 行数限制：最多返回 max_rows 行
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING

import sqlglot

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


class SQLSandboxError(Exception):
    """沙箱安全拦截。"""


class SQLSandbox:
    """SQL 执行沙箱。"""

    @staticmethod
    def _validate_readonly(sql: str) -> None:
        """AST 级别验证 SQL 是否为只读查询。"""
        try:
            parsed = sqlglot.parse(sql, dialect="mysql")
        except Exception as e:
            raise SQLSandboxError(f"SQL 解析失败: {e}") from e

        if not parsed:
            raise SQLSandboxError("无法解析 SQL")

        for stmt in parsed:
            if stmt is None:
                continue
            # 检测多语句
            if len(parsed) > 1:
                raise SQLSandboxError("禁止执行多条 SQL 语句")

            stmt_type = type(stmt).__name__.upper()
            # sqlglot 的 DML/DDL 类型判断
            if any(keyword in stmt_type for keyword in _READ_ONLY_BLOCKED):
                raise SQLSandboxError(f"禁止执行 {stmt_type} 语句（沙箱只读模式）")

            # 额外检查 AST 中的关键字
            for token in stmt.walk():
                token_type = str(getattr(token, "name", "")).upper()
                if token_type in _READ_ONLY_BLOCKED:
                    raise SQLSandboxError(f"禁止执行包含 {token_type} 的语句（沙箱只读模式）")

        # 简单字符串检测（补充 AST 可能遗漏的情况）
        stripped = sql.strip().upper()
        first_word = stripped.split()[0] if stripped.split() else ""
        if first_word in _READ_ONLY_BLOCKED:
            raise SQLSandboxError(f"禁止执行 {first_word} 语句（沙箱只读模式）")

    @staticmethod
    def _validate_single_statement(sql: str) -> None:
        """检测是否为单条语句（简单的 ; 检查，非解析级）。"""
        # 去掉注释后检查
        lines = sql.split("\n")
        cleaned = []
        for line in lines:
            # 去掉行内注释
            if "--" in line:
                line = line[: line.index("--")]
            cleaned.append(line)
        no_comments = "\n".join(cleaned)

        # 检查是否有分号分隔的多语句（最后一个分号不算）
        trimmed = no_comments.strip().rstrip(";")
        if ";" in trimmed:
            raise SQLSandboxError("禁止执行多条 SQL 语句（检测到分号分隔）")

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
        self._validate_single_statement(sql)
        self._validate_readonly(sql)

        # 2. 执行（带超时）
        try:
            result = await asyncio.wait_for(
                connector.execute(config, sql, max_rows=max_rows, timeout=timeout_seconds),
                timeout=timeout_seconds + 5,  # 额外 5 秒缓冲
            )
        except TimeoutError:
            raise TimeoutError(f"SQL 执行超时（>{timeout_seconds}秒）") from None

        return result
