"""Schema Knowledge Graph 单元测试。"""

import os
import tempfile

from app.agents.schema_graph import (
    DDLParser,
    RelationInferrer,
    SchemaGraph,
    get_schema_graph,
)

SAMPLE_DDL_ORDER = """CREATE TABLE order_main (
  order_id BIGINT PRIMARY KEY COMMENT '订单ID',
  customer_no VARCHAR(32) NOT NULL COMMENT '客户编号',
  order_amount DECIMAL(18,2) COMMENT '订单金额(元)',
  order_time DATETIME COMMENT '下单时间',
  status TINYINT COMMENT '订单状态:1待支付2已支付3已取消'
) DISTRIBUTED BY('order_id');"""

SAMPLE_DDL_CUSTOMER = """CREATE TABLE customer (
  customer_no VARCHAR(32) PRIMARY KEY COMMENT '客户编号',
  customer_name VARCHAR(128) COMMENT '客户名称',
  register_date DATE COMMENT '注册日期'
) DISTRIBUTED BY('customer_no');"""


class MockTableSchema:
    def __init__(self, table_name, ddl):
        self.table_name = table_name
        self.ddl = ddl
        self.description = ""
        self.columns = []


class TestDDLParser:
    def test_parse_table_name(self):
        meta = DDLParser.parse_ddl(SAMPLE_DDL_ORDER)
        assert meta is not None
        assert meta.name == "order_main"

    def test_parse_distribution(self):
        meta = DDLParser.parse_ddl(SAMPLE_DDL_ORDER)
        assert "DISTRIBUTED BY" in meta.distribution
        assert "order_id" in meta.distribution

    def test_parse_columns_count(self):
        meta = DDLParser.parse_ddl(SAMPLE_DDL_ORDER)
        assert len(meta.columns) == 5

    def test_primary_key_role(self):
        meta = DDLParser.parse_ddl(SAMPLE_DDL_ORDER)
        order_id = next(c for c in meta.columns if c.name == "order_id")
        assert order_id.role == "PRIMARY_KEY"
        assert order_id.label == "订单ID"

    def test_measure_role(self):
        meta = DDLParser.parse_ddl(SAMPLE_DDL_ORDER)
        amount = next(c for c in meta.columns if c.name == "order_amount")
        assert amount.role == "MEASURE"
        assert "金额" in amount.label

    def test_time_dimension_role(self):
        meta = DDLParser.parse_ddl(SAMPLE_DDL_ORDER)
        time_col = next(c for c in meta.columns if c.name == "order_time")
        assert time_col.role == "TIME_DIMENSION"

    def test_enum_role(self):
        meta = DDLParser.parse_ddl(SAMPLE_DDL_ORDER)
        status = next(c for c in meta.columns if c.name == "status")
        assert status.role == "ENUM"
        assert status.enum_values == {1: "待支付", 2: "已支付", 3: "已取消"}

    def test_foreign_key_role(self):
        meta = DDLParser.parse_ddl(SAMPLE_DDL_ORDER)
        customer_no = next(c for c in meta.columns if c.name == "customer_no")
        # customer_no is VARCHAR, ends with _no, and is not numeric → FOREIGN_KEY
        assert customer_no.role == "FOREIGN_KEY"

    def test_parse_customer_ddl(self):
        meta = DDLParser.parse_ddl(SAMPLE_DDL_CUSTOMER)
        assert meta is not None
        assert meta.name == "customer"
        assert len(meta.columns) == 3


class TestRelationInferrer:
    def test_infer_fk_to_customer(self):
        order_table = DDLParser.parse_ddl(SAMPLE_DDL_ORDER)
        customer_table = DDLParser.parse_ddl(SAMPLE_DDL_CUSTOMER)

        relationships = RelationInferrer.infer([order_table, customer_table])

        # Should find order_main.customer_no → customer.customer_no
        assert len(relationships) >= 1
        rel = relationships[0]
        assert "order_main" in rel["source"] or "order_main" in rel["target"]
        assert "customer" in rel["source"] or "customer" in rel["target"]

    def test_relationships_added_to_table_meta(self):
        order_table = DDLParser.parse_ddl(SAMPLE_DDL_ORDER)
        customer_table = DDLParser.parse_ddl(SAMPLE_DDL_CUSTOMER)
        RelationInferrer.infer([order_table, customer_table])

        # order_main should have a relationship to customer
        assert len(order_table.relationships) >= 1


class TestSchemaGraph:
    def test_build_from_schemas(self):
        schemas = [
            MockTableSchema("order_main", SAMPLE_DDL_ORDER),
            MockTableSchema("customer", SAMPLE_DDL_CUSTOMER),
        ]
        graph = SchemaGraph(db_id="test-db")
        graph.build_from_schemas(schemas)

        assert len(graph.tables) == 2
        assert "order_main" in graph.tables
        assert "customer" in graph.tables
        assert graph._built is True

    def test_exact_match_by_term(self):
        schemas = [MockTableSchema("order_main", SAMPLE_DDL_ORDER)]
        graph = SchemaGraph(db_id="test-db")
        graph.build_from_schemas(schemas)

        # Exact match on column name
        results = graph.exact_match("order_amount")
        assert len(results) >= 1
        assert results[0]["table"] == "order_main"
        assert results[0]["column"] == "order_amount"

    def test_exact_match_by_alias(self):
        schemas = [MockTableSchema("order_main", SAMPLE_DDL_ORDER)]
        graph = SchemaGraph(db_id="test-db")
        graph.build_from_schemas(schemas)

        # Match by Chinese label "订单ID"
        results = graph.exact_match("订单ID")
        assert len(results) >= 1
        assert results[0]["column"] == "order_id"

    def test_exact_match_by_amount_alias(self):
        schemas = [MockTableSchema("order_main", SAMPLE_DDL_ORDER)]
        graph = SchemaGraph(db_id="test-db")
        graph.build_from_schemas(schemas)

        # "金额" should be in the aliases of order_amount
        results = graph.exact_match("金额")
        assert len(results) >= 1
        assert results[0]["column"] == "order_amount"

    def test_find_join_path(self):
        schemas = [
            MockTableSchema("order_main", SAMPLE_DDL_ORDER),
            MockTableSchema("customer", SAMPLE_DDL_CUSTOMER),
        ]
        graph = SchemaGraph(db_id="test-db")
        graph.build_from_schemas(schemas)

        path = graph.find_join_path("order_main", "customer")
        assert path is not None
        assert len(path) >= 1

    def test_find_join_path_nonexistent(self):
        graph = SchemaGraph(db_id="test-db")
        assert graph.find_join_path("a", "b") is None

    def test_get_context_for_tables(self):
        schemas = [MockTableSchema("order_main", SAMPLE_DDL_ORDER)]
        graph = SchemaGraph(db_id="test-db")
        graph.build_from_schemas(schemas)

        context = graph.get_context_for_tables(["order_main"])
        assert "order_main" in context["tables"]
        assert "order_amount" in context["tables"]["order_main"]["columns"]
        col = context["tables"]["order_main"]["columns"]["order_amount"]
        assert col["role"] == "MEASURE"
        assert "金额" in col["label"]

    def test_save_and_load(self):
        schemas = [MockTableSchema("order_main", SAMPLE_DDL_ORDER)]
        graph = SchemaGraph(db_id="test-load-db")
        graph.build_from_schemas(schemas)

        with tempfile.TemporaryDirectory() as tmpdir:
            graph.save(data_dir=tmpdir)
            assert os.path.exists(f"{tmpdir}/test-load-db.json")

            loaded = SchemaGraph.load("test-load-db", data_dir=tmpdir)
            assert loaded is not None
            assert len(loaded.tables) == 1
            assert "order_main" in loaded.tables
            assert loaded._built is True

    def test_load_nonexistent(self):
        graph = SchemaGraph.load("nonexistent-db", data_dir="/tmp/nonexistent")
        assert graph is None

    def test_get_schema_graph_caches(self):
        from app.agents.schema_graph import _graph_instances

        g1 = get_schema_graph("cache-test")
        g2 = get_schema_graph("cache-test")
        assert g1 is g2

        # Clean up to avoid polluting other tests
        _graph_instances.pop("cache-test", None)
