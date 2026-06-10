"""Regression tests for v3.4 P0 architecture fixes."""

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.agents.graph import (
    MAX_SAME_ERROR_RETRIES,
    _clarify_node,
    _classify_user_intent,
    _greeting_fast_path,
    _refine_sql_node,
    _verify_sql_node,
    run_agent_with_ag_ui,
)
from app.agents.schema_graph import ColumnMeta, TableMeta
from app.api.connections import _refresh_schema_graph
from app.semantic.context_builder import SemanticContextBuilder


@pytest.mark.asyncio
async def test_refine_appends_new_sql_candidate():
    state = {
        "resolved_question": "查询订单",
        "sql_candidate": "SELECT missing FROM orders",
        "retry_hint": "column missing",
        "sql_history": [{"sql": "SELECT missing FROM orders", "status": "validation_failed"}],
    }
    response = SimpleNamespace(content="SELECT id FROM orders")

    with patch("app.agents.graph._call_llm", new=AsyncMock(return_value=response)):
        result = await _refine_sql_node(state)

    assert result["sql_candidate"] == "SELECT id FROM orders"
    assert len(result["sql_history"]) == 2
    assert result["sql_history"][-1] == {"sql": "SELECT id FROM orders", "status": "refined"}


@pytest.mark.asyncio
async def test_verify_stops_retrying_repeated_error():
    sql = "SELECT missing FROM orders"
    repeated_history = [
        {
            "sql": sql,
            "status": "validation_failed",
            "fingerprint": "placeholder",
        }
        for _ in range(MAX_SAME_ERROR_RETRIES)
    ]

    with patch("app.sql.semantic_validator.SemanticValidator.validate") as validate:
        validate.return_value = SimpleNamespace(
            valid=False,
            missing_intents=["缺失字段"],
            extra_intents=[],
            repair_hint="补充字段",
        )
        from app.sql.error_classifier import ErrorClassifier

        fingerprint = ErrorClassifier().make_fingerprint("缺失字段", sql).fingerprint
        for item in repeated_history:
            item["fingerprint"] = fingerprint

        result = await _verify_sql_node(
            {
                "sql_candidate": sql,
                "query_ir": {"semantic_model_id": "model"},
                "sql_history": repeated_history,
            }
        )

    assert result["should_retry"] is False


@pytest.mark.asyncio
async def test_refresh_schema_graph_builds_from_connection_ddl():
    ddl = "CREATE TABLE orders (id BIGINT PRIMARY KEY, amount DECIMAL(18,2));"

    with patch("app.agents.schema_graph.build_schema_graph_from_connection") as build_graph:
        build_graph.return_value = SimpleNamespace(tables={"orders": object()})
        _refresh_schema_graph("db-1", ddl)

    build_graph.assert_called_once()
    assert build_graph.call_args.args[0] == "db-1"
    assert build_graph.call_args.args[1][0].table_name == "orders"


def test_intent_router_only_sends_explicit_data_queries_to_nl2sql():
    assert _classify_user_intent("查询所有订单", "db-1") == "nl2sql"
    assert _classify_user_intent("GBase 如何创建分布表", "db-1") == "knowledge"
    assert _classify_user_intent("查询所有订单", None) == "nl2sql"
    assert _classify_user_intent("介绍一下 GBase", "db-1") == "knowledge"
    assert _classify_user_intent("订单状态", "db-1") == "nl2sql"
    assert _classify_user_intent("payment status", "db-1") == "nl2sql"


@pytest.mark.asyncio
async def test_greeting_uses_guarded_streaming_model_reply():
    captured = {}

    async def fake_stream(model, messages):
        captured["messages"] = messages
        yield "你好，"
        yield "今天想查点什么？"

    with (
        patch("app.dependencies.get_llm_client", return_value=SimpleNamespace()) as get_client,
        patch("app.agents.graph._stream_llm_text", side_effect=fake_stream),
    ):
        events = [
            event
            async for event in _greeting_fast_path(
                user_message="你好",
                conversation_id="conversation-1",
                model="test-model",
            )
        ]

    assert "不要声称已查询数据库" in captured["messages"][0].content
    get_client.assert_called_once_with(model="test-model", task_type="greeting")
    assert any("你好，" in event for event in events)
    assert any("今天想查点什么？" in event for event in events)
    assert not any("我是 GBase 8a 数据库助手" in event for event in events)


@pytest.mark.asyncio
async def test_data_query_without_connection_asks_user_to_select_one():
    events = [
        event
        async for event in run_agent_with_ag_ui(
            user_message="查询所有订单",
            conversation_id="conversation-1",
            model="unused",
            db_connection_id=None,
        )
    ]

    assert any("请先选择一个数据库连接" in event for event in events)
    assert any("RUN_FINISHED" in event for event in events)


@pytest.mark.asyncio
async def test_focused_schema_lazily_backfills_existing_connection_graph():
    ddl = "CREATE TABLE orders (id BIGINT PRIMARY KEY);"
    result = SimpleNamespace(scalar_one_or_none=lambda: ddl)
    session = SimpleNamespace(execute=AsyncMock(return_value=result))
    built_graph = SimpleNamespace(
        tables={
            "orders": TableMeta(
                name="orders",
                columns=[ColumnMeta(name="id", data_type="BIGINT", role="PRIMARY_KEY")],
            )
        }
    )

    with (
        patch("app.agents.schema_graph.get_schema_graph", return_value=SimpleNamespace(tables={})),
        patch("app.agents.schema_graph.build_schema_graph_from_connection", return_value=built_graph) as build_graph,
    ):
        focused = await SemanticContextBuilder(session)._build_focused_schema(
            "db-1",
            metrics=[],
            dimensions=[],
            model_tables=["orders"],
        )

    build_graph.assert_called_once()
    assert focused[0].name == "orders"
    assert focused[0].columns[0]["name"] == "id"


@pytest.mark.asyncio
async def test_clarify_node_asks_planner_question():
    result = await _clarify_node(
        {
            "query_ir": {
                "unresolved": [
                    {
                        "field": "semantic_model",
                        "candidates": ["销售模型", "订单模型"],
                        "question": "请选择业务数据模型",
                    }
                ]
            }
        }
    )

    assert "请选择业务数据模型" in result["final_response"]
    assert "销售模型、订单模型" in result["final_response"]
    assert "SQL 生成未能通过验证" not in result["final_response"]
