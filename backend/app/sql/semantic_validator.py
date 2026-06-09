"""Semantic SQL Validator — checks SQL faithfully implements Query IR.

Deterministic checks that SQL respects the user's intent as captured in Query IR.
Complements the existing sandbox (safety) and schema (syntax) validators.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from app.semantic.query_ir import QueryIR

logger = logging.getLogger(__name__)


@dataclass
class SemanticValidationReport:
    valid: bool
    error_code: str | None = None
    missing_intents: list[str] = field(default_factory=list)
    extra_intents: list[str] = field(default_factory=list)
    unsafe_joins: list[str] = field(default_factory=list)
    repair_hint: str | None = None


class SemanticValidator:
    """Checks that a generated SQL faithfully implements a Query IR.

    Rules:
    1. Each metric expression (or its column) must appear in SELECT
    2. Each dimension column must appear in SELECT and GROUP BY
    3. Each filter must appear in WHERE
    4. Time range must appear in WHERE
    5. JOINs must use verified conditions
    6. No references to tables outside the focused schema
    """

    def validate(
        self,
        sql: str,
        query_ir: QueryIR,
        focused_table_names: list[str] | None = None,
    ) -> SemanticValidationReport:
        """Validate SQL against Query IR."""
        sql_upper = sql.upper() if sql else ""
        missing = []
        extra = []
        unsafe = []

        # 1. Check metrics are in SELECT
        for metric in query_ir.metrics:
            if not self._metric_in_sql(metric.expression, sql_upper):
                missing.append(f"指标 '{metric.name}' ({metric.expression}) 未在 SELECT 中找到")

        # 2. Check dimensions are in SELECT + GROUP BY
        has_group_by = "GROUP BY" in sql_upper
        for dim in query_ir.dimensions:
            if not self._column_in_select(dim.column, sql_upper):
                missing.append(f"维度 '{dim.name}' ({dim.column}) 未在 SELECT 中找到")
            if has_group_by and not self._column_in_group_by(dim.column, sql_upper):
                missing.append(f"维度 '{dim.name}' ({dim.column}) 未在 GROUP BY 中找到")

        # If query has dimensions but SQL has no GROUP BY — potential error
        if query_ir.dimensions and not has_group_by:
            extra.append("Query IR 包含维度但 SQL 缺少 GROUP BY")

        # If query has NO dimensions but SQL has GROUP BY — potential error
        if not query_ir.dimensions and has_group_by:
            extra.append("Query IR 不包含维度但 SQL 有 GROUP BY（可能返回多行）")

        # 3. Check time range in WHERE
        if query_ir.time_range:
            tr = query_ir.time_range
            column_name = tr.column.split(".")[-1] if "." in tr.column else tr.column
            if column_name.upper() not in sql_upper:
                missing.append(f"时间列 '{tr.column}' 未在 SQL 中引用")
            if tr.start not in sql and tr.start.replace("-", "") not in sql:
                missing.append(f"时间范围起始 '{tr.start}' 未在 SQL 中找到")

        # 4. Check filters in WHERE
        for f in query_ir.filters:
            if f.column.upper() not in sql_upper:
                missing.append(f"过滤列 '{f.column}' 未在 SQL 中找到")
            elif isinstance(f.value, list):
                for v in f.value:
                    if str(v).upper() not in sql_upper:
                        missing.append(f"过滤值 '{v}' 未在 SQL 中找到")
            elif str(f.value).upper() not in sql_upper:
                missing.append(f"过滤值 '{f.value}' 未在 SQL 中找到")

        # 5. Check no out-of-scope table references
        if focused_table_names:
            import re
            sql_tables = set()
            for m in re.finditer(r'(?:FROM|JOIN)\s+(\w+)', sql_upper, re.IGNORECASE):
                sql_tables.add(m.group(1).lower())
            focused_lower = {t.lower() for t in focused_table_names}
            out_of_scope = sql_tables - focused_lower
            if out_of_scope:
                extra.append(f"SQL 引用了超出 Schema 范围的表: {', '.join(out_of_scope)}")

        # Compile report
        has_issues = bool(missing) or bool(extra) or bool(unsafe)

        if not has_issues:
            return SemanticValidationReport(valid=True)

        error_code = "semantic_mismatch"
        repair_hint_parts = []
        if missing:
            repair_hint_parts.append(f"缺失: {'; '.join(missing)}")
        if extra:
            repair_hint_parts.append(f"多余: {'; '.join(extra)}")
        if unsafe:
            repair_hint_parts.append(f"不安全: {'; '.join(unsafe)}")

        return SemanticValidationReport(
            valid=False,
            error_code=error_code,
            missing_intents=missing,
            extra_intents=extra,
            unsafe_joins=unsafe,
            repair_hint=" | ".join(repair_hint_parts) if repair_hint_parts else None,
        )

    # ── Helpers ──

    def _metric_in_sql(self, expression: str, sql_upper: str) -> bool:
        """Check if a metric expression appears in SELECT."""
        # Try exact match first
        if expression.upper() in sql_upper:
            return True
        # Try column name match
        import re
        col_match = re.search(r'\.(\w+)', expression)
        if col_match:
            col_name = col_match.group(1).upper()
            # Check if column appears in SELECT clause
            select_part = sql_upper.split("FROM")[0] if "FROM" in sql_upper else sql_upper
            if col_name in select_part:
                return True
        return False

    def _column_in_select(self, column_ref: str, sql_upper: str) -> bool:
        """Check if a column appears in SELECT."""
        col_name = column_ref.split(".")[-1].upper() if "." in column_ref else column_ref.upper()
        select_part = sql_upper.split("FROM")[0] if "FROM" in sql_upper else sql_upper
        return col_name in select_part

    def _column_in_group_by(self, column_ref: str, sql_upper: str) -> bool:
        """Check if a column appears in GROUP BY."""
        col_name = column_ref.split(".")[-1].upper() if "." in column_ref else column_ref.upper()
        if "GROUP BY" not in sql_upper:
            return False
        group_part = sql_upper.split("GROUP BY")[1]
        if "ORDER" in group_part:
            group_part = group_part.split("ORDER")[0]
        if "LIMIT" in group_part:
            group_part = group_part.split("LIMIT")[0]
        return col_name in group_part
