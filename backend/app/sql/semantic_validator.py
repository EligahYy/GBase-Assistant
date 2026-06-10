"""AST-based validation that generated SQL faithfully implements Query IR."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import sqlglot
from sqlglot import exp

from app.semantic.query_ir import FilterRef, QueryIR


@dataclass
class SemanticValidationReport:
    valid: bool
    error_code: str | None = None
    missing_intents: list[str] = field(default_factory=list)
    extra_intents: list[str] = field(default_factory=list)
    unsafe_joins: list[str] = field(default_factory=list)
    repair_hint: str | None = None


class SemanticValidator:
    """Validate metrics, dimensions, predicates, joins, and schema scope."""

    def validate(
        self,
        sql: str,
        query_ir: QueryIR,
        focused_table_names: list[str] | None = None,
        verified_join_conditions: list[str] | None = None,
    ) -> SemanticValidationReport:
        missing: list[str] = []
        extra: list[str] = []
        unsafe: list[str] = []

        try:
            statement = sqlglot.parse_one(sql, dialect="mysql")
        except sqlglot.errors.ParseError as exc:
            return self._report([f"SQL AST 解析失败: {exc}"], [], [])

        select = statement.find(exp.Select)
        if select is None:
            return self._report(["SQL 中未找到 SELECT"], [], [])

        aliases = self._alias_map(statement)
        select_signatures = {
            self._normalize_expression(item.this if isinstance(item, exp.Alias) else item, aliases)
            for item in select.expressions
        }
        select_columns = self._column_keys(select.expressions, aliases)

        group = select.args.get("group")
        group_columns = self._column_keys(group.expressions if group else [], aliases)

        for metric in query_ir.metrics:
            expected = self._parse_expression(metric.expression)
            signature = self._normalize_expression(expected, {}) if expected is not None else ""
            if not signature or signature not in select_signatures:
                missing.append(f"指标 '{metric.name}' 必须使用表达式 {metric.expression}")

        for dimension in query_ir.dimensions:
            key = self._column_ref_key(dimension.column)
            if not self._contains_column(select_columns, key):
                missing.append(f"维度 '{dimension.name}' ({dimension.column}) 未在 SELECT 中找到")
            if not group or not self._contains_column(group_columns, key):
                missing.append(f"维度 '{dimension.name}' ({dimension.column}) 未在 GROUP BY 中找到")

        if not query_ir.dimensions and group:
            extra.append("Query IR 不包含维度但 SQL 有 GROUP BY")

        where = select.args.get("where")
        predicates = list(where.this.walk()) if where else []
        for filter_ref in query_ir.filters:
            if not self._filter_in_predicates(filter_ref, predicates, aliases):
                missing.append(
                    f"过滤条件未在 WHERE 中找到: {filter_ref.column} {filter_ref.operator} {filter_ref.value}"
                )

        if query_ir.time_range:
            tr = query_ir.time_range
            start_filter = FilterRef(column=tr.column, operator=">=", value=tr.start)
            end_filter = FilterRef(column=tr.column, operator="<", value=tr.end_exclusive)
            if not self._filter_in_predicates(start_filter, predicates, aliases):
                missing.append(f"时间范围起始条件缺失: {tr.column} >= {tr.start}")
            if not self._filter_in_predicates(end_filter, predicates, aliases):
                missing.append(f"时间范围结束条件缺失: {tr.column} < {tr.end_exclusive}")

        actual_tables = {table.name.lower() for table in statement.find_all(exp.Table) if table.name}
        if focused_table_names:
            out_of_scope = actual_tables - {name.lower() for name in focused_table_names}
            if out_of_scope:
                extra.append(f"SQL 引用了超出 Schema 范围的表: {', '.join(sorted(out_of_scope))}")

        allowed_joins = {
            self._normalize_condition(condition, {})
            for condition in [*(verified_join_conditions or []), *(join.condition for join in query_ir.joins)]
            if condition
        }
        actual_joins: set[str] = set()
        for join in statement.find_all(exp.Join):
            on_clause = join.args.get("on")
            if on_clause is None:
                unsafe.append(f"JOIN {join.this.sql()} 缺少 ON 条件")
                continue
            normalized = self._normalize_expression(on_clause, aliases)
            actual_joins.add(normalized)
            if normalized not in allowed_joins:
                unsafe.append(f"JOIN 条件未经验证: {on_clause.sql()}")

        for required_join in query_ir.joins:
            normalized = self._normalize_condition(required_join.condition, {})
            if normalized and normalized not in actual_joins:
                missing.append(f"可信 JOIN 条件缺失: {required_join.condition}")

        return self._report(missing, extra, unsafe)

    def _report(
        self,
        missing: list[str],
        extra: list[str],
        unsafe: list[str],
    ) -> SemanticValidationReport:
        if not missing and not extra and not unsafe:
            return SemanticValidationReport(valid=True)
        parts = []
        if missing:
            parts.append(f"缺失: {'; '.join(missing)}")
        if extra:
            parts.append(f"多余: {'; '.join(extra)}")
        if unsafe:
            parts.append(f"不安全: {'; '.join(unsafe)}")
        return SemanticValidationReport(
            valid=False,
            error_code="semantic_mismatch",
            missing_intents=missing,
            extra_intents=extra,
            unsafe_joins=unsafe,
            repair_hint=" | ".join(parts),
        )

    def _parse_expression(self, expression: str) -> exp.Expression | None:
        try:
            return sqlglot.parse_one(expression, dialect="mysql")
        except sqlglot.errors.ParseError:
            return None

    def _alias_map(self, statement: exp.Expression) -> dict[str, str]:
        aliases: dict[str, str] = {}
        for table in statement.find_all(exp.Table):
            if not table.name:
                continue
            aliases[table.name.lower()] = table.name.lower()
            if table.alias:
                aliases[table.alias.lower()] = table.name.lower()
        return aliases

    def _normalize_condition(self, condition: str, aliases: dict[str, str]) -> str:
        try:
            statement = sqlglot.parse_one(f"SELECT 1 WHERE {condition}", dialect="mysql")
            where = statement.find(exp.Where)
            return self._normalize_expression(where.this, aliases) if where else ""
        except sqlglot.errors.ParseError:
            return ""

    def _normalize_expression(self, expression: exp.Expression, aliases: dict[str, str]) -> str:
        normalized = expression.copy()
        unique_tables = set(aliases.values())
        for column in normalized.find_all(exp.Column):
            if column.table:
                column.set("table", exp.to_identifier(aliases.get(column.table.lower(), column.table.lower())))
            elif len(unique_tables) == 1:
                column.set("table", exp.to_identifier(next(iter(unique_tables))))
            column.set("this", exp.to_identifier(column.name.lower()))
        if isinstance(normalized, exp.EQ):
            left = normalized.this.sql(dialect="mysql", normalize=True)
            right = normalized.expression.sql(dialect="mysql", normalize=True)
            if right < left:
                original_left = normalized.this.copy()
                original_right = normalized.expression.copy()
                normalized.set("this", original_right)
                normalized.set("expression", original_left)
        return normalized.sql(dialect="mysql", normalize=True, pretty=False)

    def _column_keys(self, expressions: list[exp.Expression], aliases: dict[str, str]) -> set[str]:
        return {
            self._column_key(column, aliases)
            for expression in expressions
            for column in expression.find_all(exp.Column)
        }

    def _column_key(self, column: exp.Column, aliases: dict[str, str]) -> str:
        table = aliases.get(column.table.lower(), column.table.lower()) if column.table else ""
        return f"{table}.{column.name.lower()}" if table else column.name.lower()

    def _column_ref_key(self, column_ref: str) -> str:
        return column_ref.lower().strip("` ")

    def _contains_column(self, actual: set[str], expected: str) -> bool:
        if expected in actual:
            return True
        expected_name = expected.split(".")[-1]
        return any(item.split(".")[-1] == expected_name for item in actual)

    def _filter_in_predicates(
        self,
        filter_ref: FilterRef,
        predicates: list[exp.Expression],
        aliases: dict[str, str],
    ) -> bool:
        expected_column = self._column_ref_key(filter_ref.column)
        expected_operator = filter_ref.operator.upper()
        expected_values = filter_ref.value if isinstance(filter_ref.value, list) else [filter_ref.value]
        expected_values = {self._value_key(value) for value in expected_values}

        for predicate in predicates:
            operator = self._operator(predicate)
            if operator != expected_operator:
                continue
            columns = {self._column_key(column, aliases) for column in predicate.find_all(exp.Column)}
            if not self._contains_column(columns, expected_column):
                continue
            values = {self._value_key(value.this) for value in predicate.find_all(exp.Literal)}
            if expected_values.issubset(values):
                return True
        return False

    def _operator(self, predicate: exp.Expression) -> str:
        operators: list[tuple[type[exp.Expression], str]] = [
            (exp.GTE, ">="),
            (exp.LTE, "<="),
            (exp.NEQ, "!="),
            (exp.EQ, "="),
            (exp.GT, ">"),
            (exp.LT, "<"),
            (exp.Not, "NOT IN" if isinstance(predicate.this, exp.In) else "NOT"),
            (exp.In, "IN"),
            (exp.Between, "BETWEEN"),
            (exp.Like, "LIKE"),
        ]
        for expression_type, operator in operators:
            if isinstance(predicate, expression_type):
                return operator
        return ""

    def _value_key(self, value: Any) -> str:
        return str(value).strip("'\"").lower()
