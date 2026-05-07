"""GBase 8a 原生 Python 驱动适配器（gbase-connector-python）。

懒加载：未安装驱动时返回不可用状态，不阻塞启动。
已知问题处理：
- connection_timeout 必须为 int
- datetime 类型 bytes 解码 bug（自动 patch）
- 执行后必须 fetchall() 耗尽结果
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.protocols import ConnectionConfig, QueryResult, TableSchema

logger = logging.getLogger(__name__)

_DRIVER_AVAILABLE = False
_DRIVER_MODULE = None


def _patch_datetime_bug():
    """Patch GBase 8a Python 驱动的 datetime bytes 解码 bug。"""
    try:
        import gbase.connector.conversion as conv

        original_datetime = conv._DATETIME_to_python

        def _patched_datetime(value, charset=None):
            if isinstance(value, bytes):
                value = value.decode(charset or "utf-8")
            return original_datetime(value, charset)

        conv._DATETIME_to_python = _patched_datetime
        logger.debug("已应用 GBase datetime bytes 解码 patch")
    except Exception:
        pass


def _try_import():
    """尝试导入 gbase-connector-python，成功时应用已知 bug patch。"""
    global _DRIVER_AVAILABLE, _DRIVER_MODULE
    try:
        import gbase.connector

        _DRIVER_MODULE = gbase.connector
        _DRIVER_AVAILABLE = True
        _patch_datetime_bug()
        logger.info("gbase-connector-python 驱动已加载")
    except ImportError:
        _DRIVER_AVAILABLE = False
        logger.info("gbase-connector-python 未安装，native 驱动不可用")


# 首次导入时尝试加载
try:
    _try_import()
except Exception:
    _DRIVER_AVAILABLE = False


def _build_connection_kwargs(config: ConnectionConfig) -> dict:
    """构建 gbase.connector.connect 参数（对齐官方 API）。"""
    return {
        "host": config.host or "127.0.0.1",
        "port": config.port or 5258,
        "database": config.database or "",
        "user": config.username or "",
        "passwd": config.password or "",
        "connection_timeout": int(config.connection_timeout),
        "charset": "utf8mb4",
    }


class NativeConnector:
    """gbase-connector-python 适配器。"""

    @property
    def driver_name(self) -> str:
        return "native"

    def is_available(self) -> bool:
        if _DRIVER_AVAILABLE:
            return True
        # 动态重试：可能在首次导入后才安装驱动
        _try_import()
        return _DRIVER_AVAILABLE

    async def test(self, config: ConnectionConfig) -> tuple[bool, str]:
        if not _DRIVER_AVAILABLE:
            return False, "gbase-connector-python 未安装"
        conn = None
        try:
            kwargs = _build_connection_kwargs(config)
            conn = _DRIVER_MODULE.connect(**kwargs)
            cursor = conn.cursor()
            cursor.execute("SELECT 1")
            cursor.fetchall()
            cursor.close()
            return True, "连接成功"
        except Exception as e:
            return False, f"连接失败: {e}"
        finally:
            if conn and conn.is_connected():
                conn.close()

    async def fetch_schema(self, config: ConnectionConfig) -> list[TableSchema]:
        if not _DRIVER_AVAILABLE:
            raise RuntimeError("gbase-connector-python 未安装")

        kwargs = _build_connection_kwargs(config)
        conn = _DRIVER_MODULE.connect(**kwargs)
        schemas: list[TableSchema] = []

        try:
            cursor = conn.cursor()
            # 获取所有表
            cursor.execute("SHOW TABLES")
            tables = [row[0] for row in cursor.fetchall()]

            for table_name in tables:
                # 获取表结构
                cursor.execute(f"DESCRIBE `{table_name}`")
                columns = []
                column_defs = []
                for row in cursor.fetchall():
                    # DESCRIBE 返回: Field, Type, Null, Key, Default, Extra
                    col_name = row[0]
                    col_type = row[1]
                    col_null = "NULL" if row[2] == "YES" else "NOT NULL"
                    col_default = f" DEFAULT {row[4]}" if row[4] is not None else ""
                    columns.append(col_name)
                    column_defs.append(f"  {col_name} {col_type} {col_null}{col_default}")

                # 尝试获取 DISTRIBUTED BY 信息
                distributed_by = ""
                try:
                    cursor.execute(f"SHOW CREATE TABLE `{table_name}`")
                    create_stmt = cursor.fetchone()
                    if create_stmt:
                        ddl_full = create_stmt[1] if len(create_stmt) > 1 else create_stmt[0]
                        # 提取 DISTRIBUTED BY 或 REPLICATED 子句
                        ddl_upper = ddl_full.upper()
                        if "DISTRIBUTED BY" in ddl_upper:
                            idx = ddl_upper.find("DISTRIBUTED BY")
                            distributed_by = "\n" + ddl_full[idx:].strip()
                        elif "REPLICATED" in ddl_upper:
                            idx = ddl_upper.find("REPLICATED")
                            distributed_by = "\n" + ddl_full[idx:].strip()
                except Exception:
                    pass

                ddl = f"CREATE TABLE `{table_name}` (\n" + ",\n".join(column_defs) + "\n)" + distributed_by + ";"
                from app.protocols import TableSchema

                schemas.append(
                    TableSchema(
                        table_name=table_name,
                        ddl=ddl,
                        description="",
                        columns=columns,
                    )
                )
            cursor.close()
        finally:
            if conn.is_connected():
                conn.close()

        return schemas

    async def execute(
        self,
        config: ConnectionConfig,
        sql: str,
        max_rows: int = 1000,
        timeout: int = 30,
    ) -> QueryResult:
        if not _DRIVER_AVAILABLE:
            raise RuntimeError("gbase-connector-python 未安装")

        kwargs = _build_connection_kwargs(config)
        conn = _DRIVER_MODULE.connect(**kwargs)
        start_time = time.perf_counter()

        try:
            cursor = conn.cursor()
            cursor.execute(sql)
            # 获取列名
            if cursor.description:
                columns = [desc[0] for desc in cursor.description]
            else:
                columns = []

            # 限制行数
            rows = cursor.fetchmany(max_rows + 1)
            truncated = len(rows) > max_rows
            if truncated:
                rows = rows[:max_rows]

            # 转换为列表的列表（JSON 可序列化）
            rows_serializable = []
            for row in rows:
                clean_row = []
                for val in row:
                    # 处理 datetime/date/time 类型
                    if hasattr(val, "isoformat"):
                        clean_row.append(val.isoformat())
                    else:
                        clean_row.append(val)
                rows_serializable.append(clean_row)

            # 耗尽剩余结果
            cursor.fetchall()
            cursor.close()

            elapsed_ms = (time.perf_counter() - start_time) * 1000
            from app.protocols import QueryResult

            return QueryResult(
                columns=columns,
                rows=rows_serializable,
                row_count=len(rows_serializable),
                execution_time_ms=round(elapsed_ms, 2),
                truncated=truncated,
            )
        finally:
            if conn.is_connected():
                conn.close()
