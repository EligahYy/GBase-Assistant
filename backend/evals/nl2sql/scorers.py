"""NL2SQL Eval Scorers — 多维度评估指标。

评估维度：
- table_recall: 预期表是否被引用
- column_recall: 预期列是否被引用
- sql_pattern_match: SQL 中是否包含预期模式
- execution_success: SQL 是否成功执行
- row_count_match: 返回行数是否与预期一致（有容差）
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class ScoreResult:
    """单个用例的评分结果。"""

    case_id: str
    passed: bool
    scores: dict[str, float] = field(default_factory=dict)
    details: dict[str, str] = field(default_factory=dict)


def score_table_recall(referenced_tables: list[str], expected_tables: list[str]) -> float:
    """表召回率：预期表中有多少被实际引用。"""
    if not expected_tables:
        return 1.0
    referenced_lower = {t.lower() for t in referenced_tables}
    expected_lower = {t.lower() for t in expected_tables}
    matched = expected_lower & referenced_lower
    return len(matched) / len(expected_lower)


def score_column_recall(referenced_columns: list[str], expected_columns: list[str]) -> float:
    """列召回率：预期列中有多少被实际引用。"""
    if not expected_columns:
        return 1.0
    referenced_lower = {c.lower() for c in referenced_columns}
    expected_lower = {c.lower() for c in expected_columns}
    matched = expected_lower & referenced_lower
    return len(matched) / len(expected_lower)


def score_sql_pattern(sql: str, expected_patterns: list[str]) -> float:
    """SQL 模式匹配：每个预期关键词/模式是否出现在 SQL 中。"""
    if not expected_patterns:
        return 1.0
    sql_upper = sql.upper() if sql else ""
    matched = sum(1 for p in expected_patterns if p.upper() in sql_upper)
    return matched / len(expected_patterns)


def score_execution_success(status: str | None, sql: str | None) -> float:
    """SQL 是否成功执行。"""
    if status == "completed":
        return 1.0
    if sql is None:
        return 0.0
    return 0.0


def score_row_count(actual: int | None, expected: int | None) -> float:
    """行数匹配。空结果或近似匹配给部分分。"""
    if expected is None:
        return 1.0  # 不检查行数
    if actual is None:
        return 0.0
    if actual == expected:
        return 1.0
    # 容差：同数量级给半分
    if expected > 0 and 0.5 <= actual / expected <= 2.0:
        return 0.5
    return 0.0


def score_case(
    case_id: str,
    sql: str | None,
    status: str | None,
    referenced_tables: list[str],
    referenced_columns: list[str],
    actual_row_count: int | None,
    expected: dict,
) -> ScoreResult:
    """综合评分一个用例。"""
    scores = {}
    details = {}

    # Table recall
    tr = score_table_recall(referenced_tables, expected.get("tables", []))
    scores["table_recall"] = tr
    if tr < 1.0:
        details["table_recall"] = f"expected {expected['tables']}, got {referenced_tables}"

    # Column recall
    cr = score_column_recall(referenced_columns, expected.get("columns", []))
    scores["column_recall"] = cr
    if cr < 1.0:
        details["column_recall"] = f"expected {expected['columns']}, got {referenced_columns}"

    # SQL pattern
    sp = score_sql_pattern(sql or "", expected.get("sql_pattern", []))
    scores["sql_pattern"] = sp
    if sp < 1.0:
        details["sql_pattern"] = f"expected patterns {expected.get('sql_pattern', [])}"

    # Execution
    es = score_execution_success(status, sql)
    scores["execution_success"] = es
    if es < 1.0:
        details["execution"] = f"status={status}, sql={str(sql)[:100] if sql else 'N/A'}"

    # Row count
    rc = score_row_count(actual_row_count, expected.get("row_count"))
    scores["row_count"] = rc
    if rc < 1.0:
        details["row_count"] = f"expected {expected.get('row_count')}, got {actual_row_count}"

    # Overall: weighted average
    weights = {
        "table_recall": 0.20,
        "column_recall": 0.15,
        "sql_pattern": 0.30,
        "execution_success": 0.25,
        "row_count": 0.10,
    }
    overall = sum(scores.get(k, 0) * w for k, w in weights.items())

    return ScoreResult(
        case_id=case_id,
        passed=overall >= 0.75,
        scores={"overall": round(overall, 3), **{k: round(v, 3) for k, v in scores.items()}},
        details=details,
    )


def aggregate_results(results: list[ScoreResult]) -> dict:
    """汇总所有用例的评分。"""
    if not results:
        return {}

    n = len(results)
    passed = sum(1 for r in results if r.passed)

    metric_avgs = {}
    for key in results[0].scores:
        metric_avgs[key] = round(sum(r.scores.get(key, 0) for r in results) / n, 3)

    return {
        "total_cases": n,
        "passed": passed,
        "failed": n - passed,
        "pass_rate": round(passed / n, 3) if n > 0 else 0,
        "avg_scores": metric_avgs,
    }
