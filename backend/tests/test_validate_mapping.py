"""Tests for SchemaGraph.validate_mapping() — supervisor check validation."""

from app.agents.schema_graph import ColumnMeta, SchemaGraph, TableMeta


def make_graph():
    """Create a test SchemaGraph with two tables."""
    graph = SchemaGraph(db_id="test")
    t1 = TableMeta(
        name="orders",
        label="订单表",
        columns=[
            ColumnMeta(name="id", data_type="INT", role="PRIMARY_KEY"),
            ColumnMeta(name="amount", data_type="DECIMAL(12,2)", role="MEASURE", label="订单金额"),
        ],
    )
    t2 = TableMeta(
        name="users",
        label="用户表",
        columns=[
            ColumnMeta(name="id", data_type="INT", role="PRIMARY_KEY"),
            ColumnMeta(name="name", data_type="VARCHAR(50)", role="UNKNOWN", label="用户名"),
        ],
    )
    graph.tables = {"orders": t1, "users": t2}
    graph._built = True
    return graph


def test_validate_mapping_all_valid():
    graph = make_graph()
    result = graph.validate_mapping(
        tables=["orders", "users"],
        columns={"orders": ["id", "amount"], "users": ["id", "name"]},
    )
    assert result["valid"] is True
    assert result["errors"] == []


def test_validate_mapping_table_not_found():
    graph = make_graph()
    result = graph.validate_mapping(
        tables=["orders", "nonexistent"],
        columns={"orders": ["id"], "nonexistent": ["x"]},
    )
    assert result["valid"] is False
    assert any("nonexistent" in e for e in result["errors"])


def test_validate_mapping_column_not_found():
    graph = make_graph()
    result = graph.validate_mapping(
        tables=["orders"],
        columns={"orders": ["id", "missing_column"]},
    )
    assert result["valid"] is False
    assert any("missing_column" in e for e in result["errors"])


def test_validate_mapping_no_columns_specified():
    graph = make_graph()
    result = graph.validate_mapping(
        tables=["orders", "users"],
        columns={"orders": ["id"], "users": []},
    )
    assert result["valid"] is True  # no errors, but has warnings
    assert len(result["warnings"]) >= 1
    assert any("users" in w for w in result["warnings"])
