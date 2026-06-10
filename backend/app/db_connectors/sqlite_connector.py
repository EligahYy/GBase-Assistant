"""SQLite connector for local end-to-end NL2SQL development."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

import aiosqlite

from app.config import BASE_DIR
from app.protocols import ConnectionConfig, QueryResult, TableSchema


def resolve_sqlite_path(database: str) -> Path:
    """Resolve relative SQLite database paths from the backend directory."""
    path = Path(database).expanduser()
    return path if path.is_absolute() else BASE_DIR / path


class SQLiteConnector:
    """Execute the portable subset of generated GBase SQL against SQLite."""

    @property
    def driver_name(self) -> str:
        return "sqlite"

    async def test(self, config: ConnectionConfig) -> tuple[bool, str]:
        path = resolve_sqlite_path(config.database)
        if not path.exists():
            return False, f"SQLite 数据库不存在: {path}"
        try:
            async with aiosqlite.connect(path) as conn:
                await conn.execute("SELECT 1")
            return True, f"SQLite 连接成功: {path}"
        except Exception as exc:
            return False, f"SQLite 连接失败: {exc}"

    async def fetch_schema(self, config: ConnectionConfig) -> list[TableSchema]:
        path = resolve_sqlite_path(config.database)
        if not path.exists():
            raise FileNotFoundError(f"SQLite 数据库不存在: {path}")

        schemas: list[TableSchema] = []
        async with aiosqlite.connect(path) as conn:
            cursor = await conn.execute(
                """
                SELECT name, sql
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
                """
            )
            for table_name, ddl in await cursor.fetchall():
                columns_cursor = await conn.execute(f"PRAGMA table_info(`{table_name}`)")
                columns = [row[1] for row in await columns_cursor.fetchall()]
                schemas.append(
                    TableSchema(
                        table_name=table_name,
                        ddl=f"{ddl};" if ddl and not ddl.rstrip().endswith(";") else ddl,
                        description="SQLite 本地开发样例表",
                        columns=columns,
                    )
                )
        return schemas

    async def execute(
        self,
        config: ConnectionConfig,
        sql: str,
        max_rows: int = 1000,
        timeout: int = 30,
    ) -> QueryResult:
        path = resolve_sqlite_path(config.database)
        if not path.exists():
            raise FileNotFoundError(f"SQLite 数据库不存在: {path}")

        async def _run() -> QueryResult:
            start = time.perf_counter()
            uri = f"file:{path}?mode=ro"
            async with aiosqlite.connect(uri, uri=True) as conn:
                cursor = await conn.execute(sql)
                columns = [column[0] for column in cursor.description or []]
                rows = await cursor.fetchmany(max_rows + 1)
                truncated = len(rows) > max_rows
                rows = rows[:max_rows]
            return QueryResult(
                columns=columns,
                rows=[list(row) for row in rows],
                row_count=len(rows),
                execution_time_ms=round((time.perf_counter() - start) * 1000, 2),
                truncated=truncated,
            )

        async with asyncio.timeout(timeout):
            return await _run()
