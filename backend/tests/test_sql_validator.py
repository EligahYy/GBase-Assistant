"""Tests for SQL validator: syntax, dialect compliance, schema cross-reference."""
from __future__ import annotations

import pytest

from app.protocols import TableSchema
from app.sql.validator import (
    extract_sql_from_markdown,
    validate_sql,
)


class TestSyntaxValidation:
    """Layer 1: sqlglot syntax parsing."""

    def test_valid_select(self):
        result = validate_sql("SELECT id, name FROM users")
        assert result.is_valid is True
        assert result.errors == []

    def test_invalid_syntax(self):
        result = validate_sql("SELECT FROM")
        assert result.is_valid is False
        assert any("语法" in e or "ParseError" in e for e in result.errors)

    def test_empty_sql(self):
        result = validate_sql("")
        assert result.is_valid is False


class TestDialectCompliance:
    """Layer 2: GBase 8a dialect rules."""

    def test_for_update_blocked(self):
        result = validate_sql("SELECT * FROM users WHERE id = 1 FOR UPDATE")
        assert result.is_valid is False
        assert any("FOR UPDATE" in e for e in result.errors)

    def test_lock_tables_blocked(self):
        result = validate_sql("LOCK TABLES users READ")
        assert result.is_valid is False
        assert any("LOCK TABLES" in e for e in result.errors)

    def test_create_trigger_blocked(self):
        result = validate_sql("CREATE TRIGGER trg AFTER INSERT ON users BEGIN END")
        assert result.is_valid is False
        assert any("触发器" in e or "TRIGGER" in e for e in result.errors)

    def test_create_event_blocked(self):
        result = validate_sql("CREATE EVENT ev ON SCHEDULE EVERY 1 HOUR DO SELECT 1")
        assert result.is_valid is False
        assert any("EVENT" in e for e in result.errors)

    def test_dml_warning(self):
        result = validate_sql("INSERT INTO users (name) VALUES ('test')")
        assert result.is_valid is True
        assert any("DML" in w for w in result.warnings)

    def test_drop_warning(self):
        result = validate_sql("DROP TABLE users")
        assert result.is_valid is True
        assert any("DROP" in w for w in result.warnings)

    def test_select_star_warning(self):
        result = validate_sql("SELECT * FROM users")
        assert result.is_valid is True
        assert any("SELECT *" in w for w in result.warnings)


class TestGBaseDDLRules:
    """GBase 8a specific DDL: DISTRIBUTED BY / REPLICATED."""

    def test_distributed_by_valid(self):
        sql = "CREATE TABLE t (id INT, name VARCHAR(20)) DISTRIBUTED BY('id')"
        result = validate_sql(sql)
        assert result.is_valid is True

    def test_distributed_by_column_missing(self):
        sql = "CREATE TABLE t (id INT, name VARCHAR(20)) DISTRIBUTED BY('nonexistent')"
        result = validate_sql(sql)
        assert result.is_valid is False
        assert any("DISTRIBUTED BY" in e and "不存在" in e for e in result.errors)

    def test_replicated_and_distributed_mutual_exclusive(self):
        sql = "CREATE TABLE t (id INT) REPLICATED DISTRIBUTED BY('id')"
        result = validate_sql(sql)
        assert result.is_valid is False
        assert any("REPLICATED" in e and "DISTRIBUTED BY" in e for e in result.errors)

    def test_replicated_alone_valid(self):
        sql = "CREATE TABLE dim (id INT, name VARCHAR(20)) REPLICATED"
        result = validate_sql(sql)
        assert result.is_valid is True


class TestSchemaCrossReference:
    """Layer 3: Schema table/column reference checks."""

    @pytest.fixture
    def sample_schemas(self) -> list[TableSchema]:
        return [
            TableSchema(
                table_name="users",
                ddl="CREATE TABLE users (id INT, name VARCHAR(20), age INT)",
                columns=["id", "name", "age"],
            ),
            TableSchema(
                table_name="orders",
                ddl="CREATE TABLE orders (order_id INT, user_id INT, amount DECIMAL(10,2))",
                columns=["order_id", "user_id", "amount"],
            ),
        ]

    def test_unknown_table_warning(self, sample_schemas):
        result = validate_sql("SELECT * FROM unknown_table", sample_schemas)
        assert any("unknown_table" in w for w in result.warnings)

    def test_known_table_no_warning(self, sample_schemas):
        result = validate_sql("SELECT * FROM users", sample_schemas)
        assert not any("users" in w and "未找到" in w for w in result.warnings)

    def test_unknown_column_warning(self, sample_schemas):
        result = validate_sql("SELECT unknown_col FROM users", sample_schemas)
        assert any("unknown_col" in w for w in result.warnings)

    def test_known_column_no_warning(self, sample_schemas):
        result = validate_sql("SELECT name, age FROM users", sample_schemas)
        assert not any("name" in w for w in result.warnings)
        assert not any("age" in w for w in result.warnings)

    def test_alias_column_check(self, sample_schemas):
        result = validate_sql("SELECT u.unknown_col FROM users u", sample_schemas)
        assert any("unknown_col" in w and "users" in w for w in result.warnings)

    def test_alias_known_column_ok(self, sample_schemas):
        result = validate_sql("SELECT u.name FROM users u", sample_schemas)
        assert not any("name" in w for w in result.warnings)

    def test_count_star_bypasses_column_check(self, sample_schemas):
        result = validate_sql("SELECT COUNT(*) FROM users", sample_schemas)
        assert not any("*" in w and "列" in w for w in result.warnings)


class TestJoinChecks:
    """JOIN condition validation."""

    def test_join_without_on_warning(self):
        result = validate_sql("SELECT * FROM users JOIN orders")
        assert any("JOIN 缺少 ON" in w or "笛卡尔积" in w for w in result.warnings)

    def test_join_with_on_no_warning(self):
        result = validate_sql("SELECT * FROM users JOIN orders ON users.id = orders.user_id")
        assert not any("JOIN 缺少 ON" in w for w in result.warnings)


class TestGroupByChecks:
    """GROUP BY compliance validation."""

    def test_group_by_missing_column_warning(self):
        result = validate_sql("SELECT department, name, COUNT(*) FROM employees GROUP BY department")
        assert any("GROUP BY 中缺少" in w and "name" in w for w in result.warnings)

    def test_group_by_all_columns_ok(self):
        result = validate_sql("SELECT department, name, COUNT(*) FROM employees GROUP BY department, name")
        assert not any("GROUP BY 中缺少" in w for w in result.warnings)


class TestExtractSQLFromMarkdown:
    """Markdown SQL extraction utility."""

    def test_extract_sql_code_block(self):
        text = "```sql\nSELECT * FROM users\n```"
        assert extract_sql_from_markdown(text) == "SELECT * FROM users"

    def test_extract_plain_code_block(self):
        text = "```\nSELECT * FROM users\n```"
        assert extract_sql_from_markdown(text) == "SELECT * FROM users"

    def test_extract_direct_sql(self):
        text = "Here is the query: SELECT id FROM users"
        assert extract_sql_from_markdown(text) == "SELECT id FROM users"

    def test_no_sql_found(self):
        text = "Just some text without SQL"
        assert extract_sql_from_markdown(text) is None

    def test_empty_string(self):
        assert extract_sql_from_markdown("") is None
