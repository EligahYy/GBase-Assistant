"""Create an idempotent SQLite NL2SQL demo environment."""

from __future__ import annotations

import asyncio
import json
import sqlite3
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from app.agents.schema_graph import build_schema_graph_from_connection
from app.config import BASE_DIR, get_settings
from app.database import init_db
from app.knowledge.loader import _parse_ddl_to_schemas

CONNECTION_ID = "sqlite-demo-sales"
MODEL_ID = "sqlite-demo-sales-model"
DEMO_DB = BASE_DIR / "data" / "nl2sql_demo.db"
SCHEMA_FILE = BASE_DIR / "config" / "sqlite_demo_schema.sql"
DATA_FILE = BASE_DIR / "config" / "test_data.sql"


DIMENSIONS = [
    ("dim-region", "区域", "sales_regions.region_name", ["地区", "大区"], "string"),
    ("dim-customer", "客户", "customers.customer_name", ["客户名称"], "string"),
    ("dim-member-level", "会员等级", "customers.member_level", ["会员级别"], "string"),
    ("dim-product", "产品", "products.product_name", ["商品", "产品名称"], "string"),
    ("dim-category", "产品分类", "products.category", ["品类", "分类"], "string"),
    ("dim-supplier", "供应商", "products.supplier", ["供货商"], "string"),
    ("dim-order-status", "订单状态", "orders.status", ["状态"], "string"),
    ("dim-order-date", "下单时间", "orders.order_date", ["订单日期", "日期"], "time"),
    ("dim-register-date", "注册时间", "customers.registered_at", ["注册日期"], "time"),
]

METRICS = [
    ("metric-sales", "销售额", ["销售总额", "营收", "成交额", "订单金额"], "SUM(orders.pay_amount)", ["orders"]),
    ("metric-order-count", "订单数", ["订单量", "订单数量"], "COUNT(orders.order_id)", ["orders"]),
    ("metric-avg-order", "平均订单金额", ["客单价", "平均每笔订单金额"], "AVG(orders.pay_amount)", ["orders"]),
    ("metric-product-quantity", "产品销量", ["销售数量", "卖出数量"], "SUM(order_items.quantity)", ["order_items"]),
    ("metric-product-sales", "产品销售额", ["商品销售额"], "SUM(order_items.subtotal)", ["order_items"]),
]

JOINS = [
    ("join-orders-customers", "orders", "customers", "orders.customer_id = customers.customer_id"),
    ("join-orders-regions", "orders", "sales_regions", "orders.region_id = sales_regions.region_id"),
    ("join-customers-regions", "customers", "sales_regions", "customers.region_id = sales_regions.region_id"),
    ("join-items-orders", "order_items", "orders", "order_items.order_id = orders.order_id"),
    ("join-items-products", "order_items", "products", "order_items.product_id = products.product_id"),
]

MEMBERS = {
    "dim-region": ["华东", "华南", "华北", "西南", "西北"],
    "dim-member-level": ["普通会员", "银卡会员", "金卡会员", "钻石会员"],
    "dim-category": ["电子产品", "家居用品", "食品饮料", "服装鞋帽", "图书音像"],
    "dim-order-status": [
        ("pending", "待付款", ["等待付款"]),
        ("paid", "已付款", []),
        ("shipped", "已发货", []),
        ("delivered", "已完成", ["完成", "已交付"]),
        ("cancelled", "已取消", ["取消"]),
    ],
}


def _app_db_path() -> Path:
    database_url = get_settings().database_url
    prefix = "sqlite+aiosqlite:///"
    if not database_url.startswith(prefix):
        raise RuntimeError("Demo setup currently requires the assistant metadata database to use SQLite")
    path = Path(database_url.removeprefix(prefix))
    return path if path.is_absolute() else BASE_DIR / path


def create_demo_database() -> str:
    schema = SCHEMA_FILE.read_text(encoding="utf-8")
    data = DATA_FILE.read_text(encoding="utf-8")
    DEMO_DB.parent.mkdir(parents=True, exist_ok=True)
    DEMO_DB.unlink(missing_ok=True)
    with sqlite3.connect(DEMO_DB) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.executescript(schema)
        conn.executescript(data)
        conn.commit()
    return schema


def seed_assistant_metadata(schema: str) -> None:
    now = datetime.now(UTC).isoformat()
    app_db = _app_db_path()
    with sqlite3.connect(app_db) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute(
            "DELETE FROM semantic_members WHERE dimension_id IN (SELECT id FROM semantic_dimensions WHERE semantic_model_id = ?)",
            (MODEL_ID,),
        )
        conn.execute("DELETE FROM semantic_metrics WHERE semantic_model_id = ?", (MODEL_ID,))
        conn.execute("DELETE FROM semantic_dimensions WHERE semantic_model_id = ?", (MODEL_ID,))
        conn.execute("DELETE FROM semantic_joins WHERE semantic_model_id = ?", (MODEL_ID,))
        conn.execute("DELETE FROM semantic_models WHERE id = ?", (MODEL_ID,))
        conn.execute("DELETE FROM db_connections WHERE id = ?", (CONNECTION_ID,))

        conn.execute(
            """
            INSERT INTO db_connections (
                id, name, host, port, database_name, username, password, driver_type,
                connection_tested, last_synced_at, description, schema_ddl, is_active,
                created_at, updated_at
            ) VALUES (?, ?, NULL, NULL, ?, NULL, NULL, 'sqlite', 1, ?, ?, ?, 1, ?, ?)
            """,
            (
                CONNECTION_ID,
                "SQLite 电商演示库",
                "data/nl2sql_demo.db",
                now,
                "本地 NL2SQL 全链路验证环境",
                schema,
                now,
                now,
            ),
        )
        conn.execute(
            """
            INSERT INTO semantic_models (
                id, db_connection_id, name, description, table_names, primary_table,
                enabled_for_nl2sql, schema_version, prompt_hint, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (
                MODEL_ID,
                CONNECTION_ID,
                "电商销售分析",
                "订单、客户、产品和区域销售分析模型",
                json.dumps(["orders", "customers", "sales_regions", "order_items", "products"]),
                "orders",
                "sqlite-demo-v1",
                "金额单位为元；销售额默认不限制订单状态，用户指定状态时按要求过滤。",
                now,
                now,
            ),
        )

        for metric_id, name, synonyms, expression, source_tables in METRICS:
            conn.execute(
                """
                INSERT INTO semantic_metrics (
                    id, semantic_model_id, name, synonyms, expression, source_tables,
                    default_filters, allowed_dimensions, description, status
                ) VALUES (?, ?, ?, ?, ?, ?, '[]', ?, ?, 'verified')
                """,
                (
                    metric_id,
                    MODEL_ID,
                    name,
                    json.dumps(synonyms, ensure_ascii=False),
                    expression,
                    json.dumps(source_tables),
                    json.dumps([dimension[1] for dimension in DIMENSIONS], ensure_ascii=False),
                    f"本地演示指标：{name}",
                ),
            )

        for dimension_id, name, column_ref, synonyms, data_type in DIMENSIONS:
            conn.execute(
                """
                INSERT INTO semantic_dimensions (
                    id, semantic_model_id, name, column_ref, synonyms, data_type,
                    time_granularities, hierarchy, status
                ) VALUES (?, ?, ?, ?, ?, ?, ?, NULL, 'verified')
                """,
                (
                    dimension_id,
                    MODEL_ID,
                    name,
                    column_ref,
                    json.dumps(synonyms, ensure_ascii=False),
                    data_type,
                    json.dumps(["day", "month", "year"]) if data_type == "time" else None,
                ),
            )

        for join_id, left_table, right_table, condition in JOINS:
            conn.execute(
                """
                INSERT INTO semantic_joins (
                    id, semantic_model_id, left_table, right_table, condition,
                    cardinality, source, confidence, status
                ) VALUES (?, ?, ?, ?, ?, 'many_to_one', 'manual', 1.0, 'verified')
                """,
                (join_id, MODEL_ID, left_table, right_table, condition),
            )

        for dimension_id, members in MEMBERS.items():
            for index, member in enumerate(members):
                if isinstance(member, tuple):
                    raw_value, display_value, aliases = member
                else:
                    raw_value = display_value = member
                    aliases = []
                conn.execute(
                    """
                    INSERT INTO semantic_members (
                        id, dimension_id, raw_value, display_value, aliases, frequency, status
                    ) VALUES (?, ?, ?, ?, ?, NULL, 'verified')
                    """,
                    (
                        f"member-{dimension_id}-{index}",
                        dimension_id,
                        raw_value,
                        display_value,
                        json.dumps(aliases, ensure_ascii=False),
                    ),
                )
        conn.commit()


async def main() -> None:
    await init_db()
    schema = create_demo_database()
    seed_assistant_metadata(schema)
    schemas = _parse_ddl_to_schemas(schema)
    build_schema_graph_from_connection(CONNECTION_ID, schemas)
    print(f"SQLite demo database: {DEMO_DB}")
    print(f"Assistant connection id: {CONNECTION_ID}")
    print(f"Semantic model id: {MODEL_ID}")


if __name__ == "__main__":
    asyncio.run(main())
