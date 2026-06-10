from pathlib import Path

import pytest

from app.db_connectors.connector_factory import get_available_drivers, get_connector
from app.db_connectors.sqlite_connector import SQLiteConnector
from app.protocols import ConnectionConfig


@pytest.fixture
def sqlite_config(tmp_path: Path) -> ConnectionConfig:
    import sqlite3

    path = tmp_path / "demo.db"
    with sqlite3.connect(path) as conn:
        conn.executescript(
            """
            CREATE TABLE orders (order_id INTEGER PRIMARY KEY, pay_amount NUMERIC);
            INSERT INTO orders VALUES (1, 100), (2, 200);
            """
        )
    return ConnectionConfig(
        host="",
        port=0,
        database=str(path),
        username="",
        password="",
        driver_type="sqlite",
    )


@pytest.mark.asyncio
async def test_sqlite_connector_test_schema_and_execute(sqlite_config):
    connector = SQLiteConnector()
    ok, _ = await connector.test(sqlite_config)
    schemas = await connector.fetch_schema(sqlite_config)
    result = await connector.execute(sqlite_config, "SELECT SUM(pay_amount) AS total FROM orders")

    assert ok is True
    assert schemas[0].table_name == "orders"
    assert schemas[0].columns == ["order_id", "pay_amount"]
    assert result.columns == ["total"]
    assert result.rows == [[300]]


def test_sqlite_connector_is_registered():
    assert "sqlite" in get_available_drivers()
    assert get_connector("sqlite").driver_name == "sqlite"
