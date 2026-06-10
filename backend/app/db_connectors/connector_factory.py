"""数据库连接器工厂。

按 driver_type 返回对应的 DatabaseConnector 实现。
JDBC/ODBC 预留扩展位，当前仅实现 native（gbase-connector-python）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.protocols import DatabaseConnector

logger = logging.getLogger(__name__)


# 单例缓存
_native_connector: DatabaseConnector | None = None
_sqlite_connector: DatabaseConnector | None = None


def get_connector(driver_type: str) -> DatabaseConnector | None:
    """按类型获取连接器实例。"""
    global _native_connector, _sqlite_connector

    if driver_type == "native":
        if _native_connector is None:
            from app.db_connectors.native_connector import NativeConnector

            _native_connector = NativeConnector()
        return _native_connector

    if driver_type == "sqlite":
        if _sqlite_connector is None:
            from app.db_connectors.sqlite_connector import SQLiteConnector

            _sqlite_connector = SQLiteConnector()
        return _sqlite_connector

    if driver_type in ("jdbc", "odbc"):
        logger.warning("%s 驱动尚未实现，预留扩展位", driver_type)
        return None

    if driver_type == "manual":
        return None

    logger.warning("未知的 driver_type: %s", driver_type)
    return None


def get_available_drivers() -> list[str]:
    """返回当前环境中可用的驱动类型列表。"""
    available = ["manual", "sqlite"]

    from app.db_connectors.native_connector import NativeConnector

    native = NativeConnector()
    if native.is_available():
        available.append("native")

    return available
