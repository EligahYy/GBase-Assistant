"""Regression coverage for hybrid semantic mapping and governed scope."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.graph import _fail_answer_node, _plan_query_node
from app.agents.schema_graph import SchemaGraph
from app.semantic.context_builder import SemanticContext, SemanticContextBuilder
from app.semantic.matcher import HybridSemanticMatcher, MatchResult, SemanticMatch
from app.semantic.planner import QueryPlanner, QueryPlanningError
from app.semantic.query_ir import MetricRef, QueryIR, TimeRange
from app.semantic.schema_assets import build_schema_assets
from app.sql.semantic_validator import SemanticValidator


class MeaningEmbedder:
    def __init__(self):
        self.calls: list[list[str]] = []

    async def embed(self, texts: list[str]) -> list[list[float]]:
        self.calls.append(texts)
        vectors = []
        for text in texts:
            if "营收" in text or "销售额" in text or "pay_amount" in text:
                vectors.append([1.0, 0.0, 0.0])
            elif "订单" in text:
                vectors.append([0.0, 1.0, 0.0])
            else:
                vectors.append([0.0, 0.0, 1.0])
        return vectors


@pytest.mark.asyncio
async def test_hybrid_matcher_recalls_semantic_metric_without_substring_overlap():
    metrics = [
        SimpleNamespace(
            name="销售额",
            synonyms=[],
            description="实付金额汇总",
            expression="SUM(orders.pay_amount)",
            source_tables=["orders"],
        ),
        SimpleNamespace(
            name="订单数",
            synonyms=[],
            description="订单数量",
            expression="COUNT(orders.order_id)",
            source_tables=["orders"],
        ),
    ]
    matcher = HybridSemanticMatcher(embedder=MeaningEmbedder())

    result = await matcher.match("今年营收怎么样", metrics, asset_type="metric")

    assert result.matches[0].asset.name == "销售额"
    assert result.matches[0].embedding_score == 1.0
    assert any("向量相似" in evidence for evidence in result.matches[0].evidence)


@pytest.mark.asyncio
async def test_hybrid_matcher_caches_asset_embeddings():
    embedder = MeaningEmbedder()
    metric = SimpleNamespace(
        name="销售额", synonyms=[], description="", expression="SUM(orders.pay_amount)", source_tables=["orders"]
    )
    matcher = HybridSemanticMatcher(embedder=embedder)

    await matcher.match("今年营收", [metric], asset_type="metric")
    await matcher.match("去年营收", [metric], asset_type="metric")

    assert len(embedder.calls[0]) == 2
    assert len(embedder.calls[1]) == 1


@pytest.mark.asyncio
async def test_hybrid_matcher_uses_character_similarity_for_near_business_term():
    metric = SimpleNamespace(
        name="销售额",
        synonyms=[],
        description="",
        expression="SUM(orders.pay_amount)",
        source_tables=["orders"],
    )
    matcher = HybridSemanticMatcher(min_score=0.4)

    result = await matcher.match("查询销售总额", [metric], asset_type="metric")

    assert result.matches[0].asset is metric
    assert any("字符语义相似" in evidence for evidence in result.matches[0].evidence)


@pytest.mark.asyncio
async def test_hybrid_matcher_preserves_explicit_multi_metric_intent():
    metrics = [
        SimpleNamespace(name="销售额", synonyms=[], description="", expression="", source_tables=[]),
        SimpleNamespace(name="订单数", synonyms=[], description="", expression="", source_tables=[]),
    ]
    matcher = HybridSemanticMatcher(min_score=0.4)

    result = await matcher.match("查询销售额和订单数", metrics, asset_type="metric")

    assert result.multi_intent is True
    assert result.ambiguous is False


@pytest.mark.asyncio
async def test_hybrid_matcher_requires_clarification_for_short_generic_term():
    metrics = [
        SimpleNamespace(name="销售额", synonyms=[], description="", expression="", source_tables=[]),
        SimpleNamespace(name="产品销售额", synonyms=[], description="", expression="", source_tables=[]),
    ]
    matcher = HybridSemanticMatcher(min_score=0.4)

    result = await matcher.match("查询销售", metrics, asset_type="metric")

    assert result.ambiguous is True


def test_weak_cross_category_overlap_does_not_create_false_ambiguity():
    metric = SimpleNamespace(name="订单数", status="verified")
    result = MatchResult(
        matches=[SemanticMatch(asset=metric, score=0.5, lexical_score=0.5)],
        candidates=[SemanticMatch(asset=metric, score=0.5, lexical_score=0.5)],
        ambiguous=True,
    )
    ctx = SemanticContext()

    selected = SemanticContextBuilder(SimpleNamespace())._select_matches(result, "metric", ctx)

    assert selected == [metric]
    assert ctx.ambiguities == []


def test_schema_assets_support_unseen_schema_without_comments():
    graph = SchemaGraph("billing-db")
    graph.build_from_schemas(
        [
            SimpleNamespace(
                ddl="""
                CREATE TABLE invoice_records (
                    invoice_id BIGINT PRIMARY KEY,
                    payment_status VARCHAR(32),
                    settled_amount DECIMAL(18,2),
                    issued_at TEXT
                )
                """
            )
        ]
    )

    assets = build_schema_assets("billing-db", graph)

    assert assets.model.table_names == ["invoice_records"]
    assert any(metric.expression == "COUNT(invoice_records.invoice_id)" for metric in assets.metrics)
    assert any(metric.expression == "SUM(invoice_records.settled_amount)" for metric in assets.metrics)
    assert any(dimension.column_ref == "invoice_records.payment_status" for dimension in assets.dimensions)
    assert any(
        dimension.column_ref == "invoice_records.issued_at" and dimension.data_type == "time"
        for dimension in assets.dimensions
    )


def test_schema_fallback_exposes_real_candidates_when_semantic_recall_is_empty():
    inferred = [
        SimpleNamespace(name="Payment Status", status="inferred"),
        SimpleNamespace(name="Issued At", status="inferred"),
    ]
    ctx = SemanticContext()

    selected = SemanticContextBuilder(SimpleNamespace())._select_matches(
        MatchResult(),
        "dimension",
        ctx,
        fallback_assets=inferred,
    )

    assert selected == inferred
    assert ctx.ambiguities == []


@pytest.mark.asyncio
async def test_context_builder_works_without_preconfigured_semantic_model():
    graph = SchemaGraph("billing-db")
    graph.build_from_schemas(
        [
            SimpleNamespace(
                ddl="""
                CREATE TABLE invoice_records (
                    invoice_id BIGINT PRIMARY KEY,
                    payment_status VARCHAR(32),
                    settled_amount DECIMAL(18,2)
                )
                """
            )
        ]
    )

    empty_scalars = SimpleNamespace(all=lambda: [])
    empty_result = SimpleNamespace(
        scalars=lambda: empty_scalars,
        all=lambda: [],
        scalar_one_or_none=lambda: None,
    )
    session = SimpleNamespace(execute=AsyncMock(return_value=empty_result))

    with patch("app.agents.schema_graph.get_schema_graph", return_value=graph):
        ctx = await SemanticContextBuilder(session).build("payment status", "billing-db")

    assert ctx.model.id == "schema:billing-db"
    assert ctx.inferred_assets_used is True
    assert [dimension.column_ref for dimension in ctx.dimensions] == ["invoice_records.payment_status"]
    assert ctx.ambiguities == []


@pytest.mark.asyncio
async def test_context_builder_does_not_expose_unrelated_tables_in_focused_schema():
    graph = SimpleNamespace(
        tables={
            "orders": SimpleNamespace(
                columns=[
                    SimpleNamespace(
                        name="order_id", data_type="INTEGER", role="PRIMARY_KEY", label="", comment="", enum_values=None
                    ),
                    SimpleNamespace(
                        name="pay_amount", data_type="NUMERIC", role="MEASURE", label="", comment="", enum_values=None
                    ),
                ]
            ),
            "customers": SimpleNamespace(
                columns=[
                    SimpleNamespace(
                        name="customer_id",
                        data_type="INTEGER",
                        role="PRIMARY_KEY",
                        label="",
                        comment="",
                        enum_values=None,
                    ),
                    SimpleNamespace(
                        name="phone", data_type="TEXT", role="UNKNOWN", label="", comment="", enum_values=None
                    ),
                ]
            ),
        }
    )
    metric = SimpleNamespace(expression="SUM(orders.pay_amount)", source_tables=["orders"])
    with patch("app.agents.schema_graph.get_schema_graph", return_value=graph):
        focused = await SemanticContextBuilder(SimpleNamespace())._build_focused_schema(
            "db-1",
            [metric],
            [],
            ["orders", "customers"],
            "orders",
        )

    assert [table.name for table in focused] == ["orders"]
    assert {column["name"] for column in focused[0].columns} == {"order_id", "pay_amount"}


def test_planner_rejects_model_provided_ungoverned_table_and_time_column():
    metric = SimpleNamespace(
        name="销售额",
        expression="SUM(orders.pay_amount)",
        source_tables=["orders"],
        default_filters=[],
        allowed_dimensions=[],
    )
    time_dimension = SimpleNamespace(
        name="下单时间",
        column_ref="orders.order_date",
        data_type="time",
    )
    ctx = SemanticContext(
        model=SimpleNamespace(id="sales", table_names=["orders", "customers"]),
        metrics=[metric],
        dimensions=[time_dimension],
    )
    generated = QueryIR(
        semantic_model_id="sales",
        metrics=[MetricRef(name="销售额", expression="SUM(fake.amount)")],
        required_tables=["customers"],
        time_range=TimeRange(column="customers.registered_at", start="2025-01-01", end_exclusive="2026-01-01"),
    )

    constrained = QueryPlanner(SimpleNamespace())._constrain_ir(generated, ctx)

    assert constrained.required_tables == ["orders"]
    assert constrained.time_range is None
    assert any(item.field == "time_range" for item in constrained.unresolved)


def test_planner_marks_schema_inferred_assets_as_assumptions():
    metric = SimpleNamespace(
        name="Settled Amount",
        expression="SUM(invoice_records.settled_amount)",
        source_tables=["invoice_records"],
        default_filters=[],
        allowed_dimensions=[],
        status="inferred",
    )
    dimension = SimpleNamespace(
        name="Payment Status",
        column_ref="invoice_records.payment_status",
        data_type="string",
        status="inferred",
    )
    ctx = SemanticContext(
        model=SimpleNamespace(id="schema:billing", table_names=["invoice_records"]),
        metrics=[metric],
        dimensions=[dimension],
    )
    generated = QueryIR(
        semantic_model_id="schema:billing",
        metrics=[MetricRef(name=metric.name, expression=metric.expression)],
    )

    constrained = QueryPlanner(SimpleNamespace())._constrain_ir(generated, ctx)

    assert any("尚未经过业务口径确认" in assumption for assumption in constrained.assumptions)


@pytest.mark.asyncio
async def test_context_ambiguity_is_propagated_to_query_ir():
    llm = SimpleNamespace(
        complete=AsyncMock(
            return_value=(
                '{"query_type":"aggregate","metrics":[],"dimensions":[],"required_tables":[],"unresolved":[]}',
                {},
                None,
            )
        )
    )
    ctx = SemanticContext(
        model=SimpleNamespace(id="sales", table_names=[]),
        ambiguities=[SimpleNamespace(field="metric", candidates=["销售额", "产品销售额"], question="请选择指标")],
    )

    result = await QueryPlanner(llm).plan("查询销售", ctx)

    assert result.unresolved[0].question == "请选择指标"


@pytest.mark.asyncio
async def test_planner_service_failure_is_not_returned_as_user_ambiguity():
    llm = SimpleNamespace(complete=AsyncMock(side_effect=RuntimeError("provider unavailable")))
    ctx = SemanticContext(model=SimpleNamespace(id="sales", table_names=[]))

    with pytest.raises(QueryPlanningError, match="查询计划服务暂时不可用"):
        await QueryPlanner(llm).plan("销售额", ctx)


def test_semantic_validator_accepts_unqualified_metric_in_single_table_query():
    query_ir = QueryIR(
        semantic_model_id="sales",
        metrics=[MetricRef(name="销售额", expression="SUM(orders.pay_amount)")],
    )

    report = SemanticValidator().validate("SELECT SUM(pay_amount) FROM orders", query_ir, ["orders"])

    assert report.valid is True


@pytest.mark.asyncio
async def test_plan_node_routes_planning_service_failure_as_system_error():
    with (
        patch("app.dependencies.get_llm_client", return_value=SimpleNamespace()),
        patch(
            "app.semantic.planner.QueryPlanner.plan",
            new=AsyncMock(side_effect=QueryPlanningError("查询计划服务暂时不可用")),
        ),
    ):
        state = await _plan_query_node(
            {
                "resolved_question": "销售额",
                "semantic_context": SemanticContext(model=SimpleNamespace(id="sales")),
            }
        )

    assert state["planning_error"] == "查询计划服务暂时不可用"
    assert state["should_clarify"] is False
    answer = await _fail_answer_node(state)
    assert "请稍后重试" in answer["final_response"]
    assert "请先确认" not in answer["final_response"]
