"""Regression tests for v3.4 P1 architecture fixes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.graph import _build_answer_node, _execute_sql_node, _verify_sql_node
from app.main import create_app
from app.semantic.context_builder import SemanticContext, SemanticContextBuilder
from app.semantic.planner import QueryPlanner
from app.semantic.query_ir import (
    DimensionRef,
    FilterRef,
    JoinRef,
    MetricRef,
    QueryIR,
    TimeRange,
)
from app.sql.semantic_validator import SemanticValidator


def _sales_ir() -> QueryIR:
    return QueryIR(
        semantic_model_id="sales",
        metrics=[MetricRef(name="销售额", expression="SUM(orders.pay_amount)")],
        dimensions=[DimensionRef(name="区域", column="sales_regions.region_name")],
        filters=[FilterRef(column="orders.status", operator="=", value="delivered")],
        time_range=TimeRange(
            column="orders.order_date",
            start="2025-01-01",
            end_exclusive="2026-01-01",
        ),
        joins=[JoinRef(condition="orders.region_id = sales_regions.region_id")],
    )


def test_ast_semantic_validator_accepts_aliases_and_verified_join():
    sql = """
    SELECT r.region_name, SUM(o.pay_amount)
    FROM orders o
    JOIN sales_regions r ON o.region_id = r.region_id
    WHERE o.status = 'delivered'
      AND o.order_date >= '2025-01-01'
      AND o.order_date < '2026-01-01'
    GROUP BY r.region_name
    """
    report = SemanticValidator().validate(
        sql,
        _sales_ir(),
        ["orders", "sales_regions"],
        ["orders.region_id = sales_regions.region_id"],
    )
    assert report.valid is True


def test_ast_semantic_validator_rejects_wrong_metric_missing_end_and_unsafe_join():
    sql = """
    SELECT r.region_name, o.pay_amount
    FROM orders o
    JOIN sales_regions r ON o.customer_id = r.region_id
    WHERE o.status = 'delivered' AND o.order_date >= '2025-01-01'
    GROUP BY r.region_name
    """
    report = SemanticValidator().validate(
        sql,
        _sales_ir(),
        ["orders", "sales_regions"],
        ["orders.region_id = sales_regions.region_id"],
    )
    assert report.valid is False
    assert any("必须使用表达式" in error for error in report.missing_intents)
    assert any("结束条件缺失" in error for error in report.missing_intents)
    assert any("未经验证" in error for error in report.unsafe_joins)


def test_ast_semantic_validator_requires_filter_in_where():
    ir = QueryIR(
        semantic_model_id="sales",
        filters=[FilterRef(column="orders.status", operator="=", value="delivered")],
    )
    report = SemanticValidator().validate(
        "SELECT status, 'delivered' AS expected_status FROM orders",
        ir,
        ["orders"],
    )
    assert report.valid is False
    assert any("过滤条件未在 WHERE" in error for error in report.missing_intents)


def test_query_ir_accepts_common_llm_field_aliases():
    query_ir = QueryIR.from_dict(
        {
            "semantic_model_id": "sales",
            "metrics": [{"name": "销售额", "formula": "SUM(orders.pay_amount)", "source_table": "orders"}],
            "dimensions": [{"name": "区域", "field": "sales_regions.region_name"}],
            "filters": [{"field": "orders.status", "operator": "=", "value": "delivered"}],
            "time_range": {
                "field": "orders.order_date",
                "start": "2025-01-01",
                "end": "2026-01-01",
            },
            "order_by": [{"column": "销售额", "order": "desc"}],
            "joins": [
                {
                    "left_table": "orders",
                    "right_table": "sales_regions",
                    "condition": "orders.region_id = sales_regions.region_id",
                }
            ],
        }
    )
    assert query_ir.dimensions[0].column == "sales_regions.region_name"
    assert query_ir.filters[0].column == "orders.status"
    assert query_ir.time_range.end_exclusive == "2026-01-01"
    assert query_ir.order_by[0].target == "销售额"
    assert query_ir.order_by[0].direction == "DESC"
    assert query_ir.metrics[0].expression == "SUM(orders.pay_amount)"
    assert query_ir.joins[0].condition == "orders.region_id = sales_regions.region_id"


def test_query_ir_accepts_string_unresolved_item():
    query_ir = QueryIR.from_dict(
        {
            "semantic_model_id": "sales",
            "unresolved": ["未找到与销售总额匹配的指标"],
        }
    )

    assert query_ir.unresolved[0].field == "unknown"
    assert query_ir.unresolved[0].question == "未找到与销售总额匹配的指标"


@pytest.mark.asyncio
async def test_verifier_uses_complete_schema_catalog_for_planner_time_filter():
    ctx = SemanticContext(
        focused_schema=[
            SimpleNamespace(
                name="orders",
                columns=[
                    {"name": "order_id"},
                    {"name": "pay_amount"},
                ],
            )
        ],
        schema_catalog={
            "orders": [
                "order_id",
                "order_date",
                "pay_amount",
            ]
        },
    )
    query_ir = QueryIR(
        semantic_model_id="sales",
        metrics=[MetricRef(name="销售额", expression="SUM(orders.pay_amount)")],
        time_range=TimeRange(
            column="orders.order_date",
            start="2025-01-01",
            end_exclusive="2026-01-01",
        ),
    )

    result = await _verify_sql_node(
        {
            "sql_candidate": (
                "SELECT SUM(orders.pay_amount) AS 销售额 FROM orders "
                "WHERE orders.order_date >= '2025-01-01' "
                "AND orders.order_date < '2026-01-01'"
            ),
            "query_ir": query_ir.to_dict(),
            "semantic_context": ctx,
            "sql_history": [],
        }
    )

    assert result["validation_report"]["valid"] is True
    assert result["should_retry"] is False


@pytest.mark.asyncio
async def test_verifier_does_not_retry_schema_reference_error():
    ctx = SemanticContext(
        focused_schema=[SimpleNamespace(name="orders", columns=[{"name": "pay_amount"}])],
        schema_catalog={"orders": ["pay_amount"]},
    )
    query_ir = QueryIR(
        semantic_model_id="sales",
        metrics=[MetricRef(name="销售额", expression="SUM(orders.pay_amount)")],
    )

    result = await _verify_sql_node(
        {
            "sql_candidate": "SELECT SUM(orders.pay_amount) FROM orders WHERE orders.missing_date >= '2025-01-01'",
            "query_ir": query_ir.to_dict(),
            "semantic_context": ctx,
            "sql_history": [],
        }
    )

    assert result["validation_report"]["valid"] is False
    assert result["should_retry"] is False
    assert "missing_date" in result["retry_hint"]


def test_planner_constrains_generated_ir_to_governed_definitions():
    metric = SimpleNamespace(
        name="销售额",
        expression="SUM(orders.pay_amount)",
        source_tables=["orders"],
        default_filters=[{"column": "orders.status", "operator": "=", "value": "delivered"}],
        allowed_dimensions=["区域"],
    )
    dimension = SimpleNamespace(
        id="region-dim",
        name="区域",
        column_ref="sales_regions.region_name",
    )
    join = SimpleNamespace(
        left_table="orders",
        right_table="sales_regions",
        condition="orders.region_id = sales_regions.region_id",
    )
    ctx = SemanticContext(
        model=SimpleNamespace(id="sales", table_names=["orders", "sales_regions"]),
        metrics=[metric],
        dimensions=[dimension],
        verified_joins=[join],
    )
    generated = QueryIR(
        semantic_model_id="sales",
        metrics=[MetricRef(name="销售额", expression="SUM(fake.amount)")],
        dimensions=[DimensionRef(name="区域", column="fake.region")],
        joins=[JoinRef(condition=join.condition)],
    )

    constrained = QueryPlanner(SimpleNamespace())._constrain_ir(generated, ctx)

    assert constrained.metrics[0].expression == "SUM(orders.pay_amount)"
    assert constrained.dimensions[0].column == "sales_regions.region_name"
    assert constrained.filters[0].column == "orders.status"
    assert constrained.required_tables == ["orders", "sales_regions"]


@pytest.mark.asyncio
async def test_time_question_adds_metric_compatible_governed_time_dimension():
    order_time = SimpleNamespace(
        id="order-time",
        semantic_model_id="sales",
        status="verified",
        data_type="time",
        column_ref="orders.order_date",
    )
    register_time = SimpleNamespace(
        id="register-time",
        semantic_model_id="sales",
        status="verified",
        data_type="time",
        column_ref="customers.registered_at",
    )
    result = MagicMock()
    result.scalars.return_value.all.return_value = [order_time, register_time]
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    metric = SimpleNamespace(source_tables=["orders"])

    dimensions = await SemanticContextBuilder(session)._augment_time_dimensions(
        "2025年全年销售额",
        "sales",
        [metric],
        [],
    )

    assert dimensions == [order_time]


@pytest.mark.asyncio
async def test_execution_failure_enters_bounded_repair_for_schema_error():
    result = {"status": "execution_failed", "sql": "SELECT missing FROM orders", "error": "column missing"}
    with patch("app.agents.tools.sql_tools.SubmitSQLTool.execute", new=AsyncMock(return_value=result)):
        state = await _execute_sql_node(
            {
                "sql_candidate": result["sql"],
                "db_connection_id": "db-1",
                "execution_count": 0,
                "sql_history": [{"sql": result["sql"], "status": "verified"}],
            }
        )
    assert state["should_retry"] is True
    assert state["execution_count"] == 1
    assert state["sql_history"][-1]["status"] == "execution_failed"


@pytest.mark.asyncio
async def test_connection_failure_does_not_retry_sql_generation():
    result = {"status": "execution_failed", "sql": "SELECT 1", "error": "connection timeout"}
    with patch("app.agents.tools.sql_tools.SubmitSQLTool.execute", new=AsyncMock(return_value=result)):
        state = await _execute_sql_node(
            {
                "sql_candidate": result["sql"],
                "db_connection_id": "db-1",
                "execution_count": 0,
                "sql_history": [{"sql": result["sql"], "status": "verified"}],
            }
        )
    assert state["should_retry"] is False


@pytest.mark.asyncio
async def test_answer_builder_receives_real_rows():
    captured = {}

    async def fake_stream(model, messages):
        captured["prompt"] = messages[0].content
        yield "华东销售额"
        yield "为 100"

    with patch("app.agents.graph._stream_llm_text", side_effect=fake_stream):
        result = await _build_answer_node(
            {
                "resolved_question": "华东销售额",
                "query_ir": {"semantic_model_id": "sales"},
                "query_result": {
                    "status": "completed",
                    "columns": ["region_name", "sales"],
                    "rows": [["华东", 100]],
                    "row_count": 1,
                    "execution_time_ms": 2,
                    "truncated": False,
                },
            }
        )
    assert '"rows": [["华东", 100]]' in captured["prompt"]
    assert "不要输出 markdown 表格" in captured["prompt"]
    assert result["final_response"] == "华东销售额为 100"


def test_semantic_model_api_has_single_api_prefix_and_admin_dependency():
    routes = create_app().routes
    paths = {route.path for route in routes}
    assert "/api/semantic-models" in paths
    assert "/api/api/semantic-models" not in paths
    semantic_route = next(route for route in routes if route.path == "/api/semantic-models")
    assert semantic_route.dependencies
