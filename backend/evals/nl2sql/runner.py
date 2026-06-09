"""NL2SQL Eval Runner — 可重复执行的评估框架。

用法:
  # Mock 模式 (CI, 结构验证)
  uv run python -m evals.nl2sql.runner --mock

  # 真实 LLM 模式 (准确率测量)
  uv run python -m evals.nl2sql.runner --model deepseek/deepseek-chat

输出:
  - 每个用例的评分明细
  - 汇总指标: pass_rate, avg_scores, avg_llm_calls, avg_latency
"""

from __future__ import annotations

import argparse
import asyncio
import json
import time
import sys
from dataclasses import dataclass, field
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import yaml
from langchain_core.messages import AIMessage, HumanMessage, ToolCall
from langchain_core.outputs import ChatGeneration, ChatResult

# Ensure backend is on path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from evals.nl2sql.scorers import ScoreResult, score_case, aggregate_results

# ═══════════════════════════════════════════════════════════════════════════════
# Data classes
# ═══════════════════════════════════════════════════════════════════════════════

@dataclass
class EvalResult:
    case_id: str
    question: str
    sql: str | None
    status: str | None
    referenced_tables: list[str]
    referenced_columns: list[str]
    row_count: int | None
    llm_calls: int
    latency_ms: float
    score: ScoreResult | None = None


@dataclass
class EvalReport:
    results: list[EvalResult] = field(default_factory=list)
    aggregate: dict = field(default_factory=dict)
    config: dict = field(default_factory=dict)


# ═══════════════════════════════════════════════════════════════════════════════
# LLM Mocks
# ═══════════════════════════════════════════════════════════════════════════════

def _tc(name: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[ToolCall(name=name, args=args, id=f"call_{name}")])


def _fa(answer: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[ToolCall(name="final_answer", args={"answer": answer, "sources": []}, id="call_fa")])


# Per-case mock SQL — structural validation of the eval pipeline
_CASE_SQL = {
    "agg_001": "SELECT COUNT(order_id) AS cnt FROM orders",
    "agg_002": "SELECT SUM(pay_amount) AS total FROM orders WHERE order_date >= '2025-01-01' AND order_date < '2026-01-01'",
    "agg_003": "SELECT SUM(pay_amount) AS total FROM orders",
    "agg_004": "SELECT AVG(pay_amount) AS avg_amount FROM orders",
    "agg_005": "SELECT MAX(pay_amount) AS max_amt, MIN(pay_amount) AS min_amt FROM orders",
    "filter_001": "SELECT * FROM orders WHERE status = 'cancelled'",
    "filter_002": "SELECT SUM(pay_amount) AS total FROM orders WHERE status = 'delivered'",
    "filter_003": "SELECT customer_name FROM customers WHERE member_level = '金卡会员'",
    "filter_004": "SELECT COUNT(order_id) AS cnt FROM orders WHERE order_date >= '2025-01-01' AND order_date < '2025-07-01'",
    "group_001": "SELECT r.region_name, COUNT(o.order_id) AS cnt FROM orders o JOIN sales_regions r ON o.region_id = r.region_id GROUP BY r.region_name",
    "group_002": "SELECT category, AVG(unit_price) AS avg_price FROM products GROUP BY category",
    "group_003": "SELECT customer_name, total_amount FROM customers",
    "group_004": "SELECT member_level, COUNT(*) AS cnt FROM customers GROUP BY member_level",
    "join_001": "SELECT c.customer_name, o.order_id, o.pay_amount FROM customers c JOIN orders o ON c.customer_id = o.customer_id",
    "join_002": "SELECT r.region_name, SUM(o.pay_amount) AS total FROM orders o JOIN sales_regions r ON o.region_id = r.region_id GROUP BY r.region_name ORDER BY total DESC",
    "join_003": "SELECT p.product_name, SUM(oi.quantity) AS total_qty FROM products p JOIN order_items oi ON p.product_id = oi.product_id GROUP BY p.product_name",
    "order_001": "SELECT p.product_name, SUM(oi.subtotal) AS total FROM products p JOIN order_items oi ON p.product_id = oi.product_id GROUP BY p.product_name ORDER BY total DESC LIMIT 5",
    "order_002": "SELECT customer_name, registered_at FROM customers ORDER BY registered_at ASC LIMIT 3",
    "time_001": "SELECT SUM(pay_amount) AS total FROM orders WHERE order_date >= '2025-01-01' AND order_date < '2026-01-01'",
    "time_002": "SELECT COUNT(order_id) AS cnt FROM orders WHERE order_date >= '2025-03-01' AND order_date < '2025-04-01'",
    "term_001": "SELECT SUM(pay_amount) AS total FROM orders",
    "term_002": "SELECT p.product_name, SUM(oi.quantity) AS total_qty FROM products p JOIN order_items oi ON p.product_id = oi.product_id GROUP BY p.product_name ORDER BY total_qty DESC",
    "term_003": "SELECT * FROM orders WHERE status = 'pending'",
    "complex_001": "SELECT SUM(o.pay_amount) AS total FROM orders o JOIN customers c ON o.customer_id = c.customer_id JOIN sales_regions r ON c.region_id = r.region_id WHERE c.member_level = '钻石会员' AND r.region_name = '华东'",
    "complex_002": "SELECT p.product_name, SUM(oi.quantity) AS total_qty FROM products p JOIN order_items oi ON p.product_id = oi.product_id WHERE p.supplier = '深圳智能硬件' GROUP BY p.product_name ORDER BY total_qty DESC LIMIT 1",
    "complex_003": "SELECT c.customer_name, SUM(o.pay_amount) AS total FROM customers c JOIN orders o ON c.customer_id = o.customer_id WHERE c.registered_at >= '2025-01-01' GROUP BY c.customer_name ORDER BY total DESC LIMIT 3",
}


class ScriptedLLM:
    """Returns predefined responses per case for eval structural validation."""
    def __init__(self, case_id: str):
        sql = _CASE_SQL.get(case_id, "SELECT * FROM orders LIMIT 10")
        self.responses = [
            _tc("submit_sql", {"sql": sql}),
            _fa("查询完成"),
        ]
        self.call_count = 0

    async def _agenerate(self, messages, **kwargs):
        idx = min(self.call_count, len(self.responses) - 1)
        resp = self.responses[idx]
        self.call_count += 1
        return ChatResult(generations=[ChatGeneration(message=resp)])


# ═══════════════════════════════════════════════════════════════════════════════
# SQL extraction
# ═══════════════════════════════════════════════════════════════════════════════

def _extract_tables_from_sql(sql: str | None) -> list[str]:
    """Extract table names from SQL using simple heuristics."""
    if not sql:
        return []
    import re
    sql_upper = sql.upper()
    tables = set()
    # FROM / JOIN patterns
    for m in re.finditer(r'(?:FROM|JOIN)\s+(\w+)', sql_upper, re.IGNORECASE):
        tables.add(m.group(1).lower())
    return list(tables)


def _extract_columns_from_sql(sql: str | None) -> list[str]:
    """Check if expected column names appear in SQL (substring match)."""
    if not sql:
        return []
    import re
    cols = set()
    sql_lower = sql.lower()
    # table.column patterns
    for m in re.finditer(r'(\w+)\.(\w+)', sql_lower):
        cols.add(m.group(2))
    # Any word that matches an expected column pattern in the scorer
    # Just return everything that looks like a column reference
    # Strip SQL keywords
    keywords = {"select", "from", "where", "and", "or", "not", "in", "on", "as",
                "join", "left", "right", "inner", "outer", "group", "order", "by",
                "limit", "offset", "asc", "desc", "having", "between", "like", "is",
                "null", "count", "sum", "avg", "max", "min", "distinct", "all",
                "case", "when", "then", "else", "end", "cast", "exists"}
    # Extract identifiers after SELECT (before FROM)
    select_match = re.search(r'select\s+(.*?)\s+from', sql_lower, re.DOTALL)
    if select_match:
        select_text = select_match.group(1)
        # Split by comma, extract column names
        for part in select_text.split(','):
            part = part.strip()
            # Extract words that aren't keywords or functions
            words = re.findall(r'\b([a-z_]\w*)\b', part)
            for w in words:
                if w not in keywords and not w.isdigit():
                    cols.add(w)
    return list(cols)


# ═══════════════════════════════════════════════════════════════════════════════
# Runner
# ═══════════════════════════════════════════════════════════════════════════════

def _load_cases() -> list[dict]:
    cases_path = Path(__file__).parent / "cases.yaml"
    with open(cases_path, encoding="utf-8") as f:
        data = yaml.safe_load(f)
    return data.get("cases", [])


async def run_case(case: dict, mock: bool = False, model: str | None = None) -> EvalResult:
    """Run a single eval case and return the result."""
    case_id = case["id"]
    question = case["question"]
    expected = case.get("expected", {})

    llm = ScriptedLLM(case_id) if mock else None

    start = time.monotonic()

    try:
        if mock:
            with (
                patch("app.agents.graph.LiteLLMChatAdapter", return_value=llm),
                patch("app.dependencies.get_llm_client", return_value=MagicMock()),
            ):
                from app.agents.graph import build_graph
                graph = build_graph(db_connection_id="eval-db")
                state = {
                    "messages": [HumanMessage(content=question)],
                    "db_connection_id": "eval-db",
                    "cb": {},
                }
                result = await graph.ainvoke(state, {"configurable": {"thread_id": f"eval-{case_id}"}})
                llm_calls = llm.call_count
        else:
            # Real LLM mode — defer to Phase 1 when API key is available
            return EvalResult(
                case_id=case_id, question=question,
                sql=None, status="skipped",
                referenced_tables=[], referenced_columns=[],
                row_count=None, llm_calls=0, latency_ms=0,
            )
    except Exception as e:
        return EvalResult(
            case_id=case_id, question=question,
            sql=None, status=f"error: {e}",
            referenced_tables=[], referenced_columns=[],
            row_count=None, llm_calls=0 if not mock else llm.call_count,
            latency_ms=(time.monotonic() - start) * 1000,
        )

    latency_ms = (time.monotonic() - start) * 1000

    # Extract SQL from messages
    sql = None
    status = "not_found"
    row_count = None
    cb = result.get("cb", {})
    sql_state = cb.get("sql", {}) if cb else {}
    if sql_state:
        sql = sql_state.get("generated_sql")
        status = sql_state.get("status", "not_found")
        last_result = sql_state.get("last_result")
        if isinstance(last_result, dict):
            row_count = last_result.get("row_count")

    referenced_tables = _extract_tables_from_sql(sql)
    referenced_columns = _extract_columns_from_sql(sql)

    return EvalResult(
        case_id=case_id,
        question=question,
        sql=sql,
        status=status,
        referenced_tables=referenced_tables,
        referenced_columns=referenced_columns,
        row_count=row_count,
        llm_calls=llm_calls,
        latency_ms=latency_ms,
    )


async def run_eval(mock: bool = False, model: str | None = None) -> EvalReport:
    """Run all eval cases and produce a report."""
    cases = _load_cases()
    results = []

    for case in cases:
        eval_result = await run_case(case, mock=mock, model=model)
        score = score_case(
            case_id=case["id"],
            sql=eval_result.sql,
            status=eval_result.status,
            referenced_tables=eval_result.referenced_tables,
            referenced_columns=eval_result.referenced_columns,
            actual_row_count=eval_result.row_count,
            expected=case.get("expected", {}),
        )
        eval_result.score = score
        results.append(eval_result)

    aggregate = aggregate_results([r.score for r in results if r.score])

    # Compute avg latency and llm calls
    completed = [r for r in results if r.status not in ("skipped",) and not (r.status or "").startswith("error")]
    if completed:
        avg_latency = sum(r.latency_ms for r in completed) / len(completed)
        avg_llm_calls = sum(r.llm_calls for r in completed) / len(completed)
        aggregate["avg_latency_ms"] = round(avg_latency, 1)
        aggregate["avg_llm_calls"] = round(avg_llm_calls, 1)

    return EvalReport(
        results=results,
        aggregate=aggregate,
        config={"mock": mock, "model": model, "total_cases": len(cases)},
    )


def print_report(report: EvalReport):
    """Print eval report to stdout."""
    print("\n" + "=" * 70)
    print("NL2SQL EVAL REPORT")
    print("=" * 70)
    print(f"  Mode: {'mock' if report.config.get('mock') else 'live'} ({report.config.get('model', 'N/A')})")
    print(f"  Cases: {report.config['total_cases']}")

    agg = report.aggregate
    print(f"\n  ── Aggregate ──")
    print(f"  Pass Rate:  {agg.get('pass_rate', 0) * 100:.1f}% ({agg.get('passed', 0)}/{agg.get('total_cases', 0)})")
    if "avg_llm_calls" in agg:
        print(f"  Avg LLM Calls: {agg['avg_llm_calls']}")
    if "avg_latency_ms" in agg:
        print(f"  Avg Latency: {agg['avg_latency_ms']:.1f}ms")

    avg_scores = agg.get("avg_scores", {})
    if avg_scores:
        print(f"\n  ── Avg Scores ──")
        for k, v in avg_scores.items():
            print(f"  {k}: {v:.3f}")

    print(f"\n  ── Per-Case ──")
    for r in report.results:
        status_icon = "✅" if (r.score and r.score.passed) else "❌"
        score_str = ""
        if r.score:
            overall = r.score.scores.get("overall", 0)
            score_str = f" [{overall:.2f}]"
            if r.score.details:
                score_str += f" ({', '.join(r.score.details.keys())})"
        sql_preview = (r.sql or "N/A")[:80]
        print(f"  {status_icon} {r.case_id}: {r.question[:50]}{score_str}")
        print(f"     SQL: {sql_preview}")

    print("\n" + "=" * 70)


# ═══════════════════════════════════════════════════════════════════════════════
# CLI
# ═══════════════════════════════════════════════════════════════════════════════

def main():
    parser = argparse.ArgumentParser(description="NL2SQL Eval Runner")
    parser.add_argument("--mock", action="store_true", default=True, help="Use mock LLM (default)")
    parser.add_argument("--live", action="store_true", help="Use real LLM (needs API key)")
    parser.add_argument("--model", type=str, default="deepseek/deepseek-chat", help="Model for live mode")
    parser.add_argument("--output", type=str, help="JSON output file")
    args = parser.parse_args()

    mock = not args.live
    report = asyncio.run(run_eval(mock=mock, model=args.model))

    print_report(report)

    if args.output:
        output_data = {
            "config": report.config,
            "aggregate": report.aggregate,
            "results": [
                {
                    "case_id": r.case_id,
                    "question": r.question,
                    "sql": r.sql,
                    "status": r.status,
                    "llm_calls": r.llm_calls,
                    "latency_ms": r.latency_ms,
                    "score": r.score.scores if r.score else None,
                    "details": r.score.details if r.score else None,
                }
                for r in report.results
            ],
        }
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(output_data, f, ensure_ascii=False, indent=2)
        print(f"\nReport saved to {args.output}")


if __name__ == "__main__":
    main()
