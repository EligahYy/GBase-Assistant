"""SQL Error Classifier — fingerprints errors for bounded repair.

Classifies SQL errors into categories so the repair loop can:
- Apply category-specific repair strategies
- Enforce per-category retry limits
- Avoid retrying the same error fingerprint
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)

# Error categories from the review doc
ERROR_CATEGORIES = [
    "wrong_model",       # Semantic model selection error
    "wrong_metric",      # Metric mapping error
    "wrong_dimension",   # Dimension mapping error
    "wrong_member",      # Member value linking error
    "wrong_join",        # JOIN selection/condition error
    "missing_filter",    # Required filter not applied
    "wrong_time_range",  # Time range parsing error
    "wrong_aggregation", # Aggregation logic error (missing GROUP BY, etc.)
    "dialect_error",     # GBase 8a syntax error
    "execution_error",   # Runtime error (timeout, connection, etc.)
    "semantic_mismatch", # SQL doesn't match Query IR
    "unknown",           # Uncategorized
]


@dataclass
class ErrorFingerprint:
    category: str
    fingerprint: str       # hash of error message + SQL pattern
    error_message: str
    sql_snippet: str       # first 100 chars of SQL
    retry_count: int = 0   # how many times this fingerprint has been retried
    max_retries: int = 2   # per-fingerprint limit


class ErrorClassifier:
    """Classifies SQL errors into categories for targeted repair."""

    def classify(self, error_message: str, sql: str | None = None) -> str:
        """Classify an error message into a category."""
        msg_lower = (error_message or "").lower()
        sql_upper = (sql or "").upper()

        # Schema/semantic errors
        if any(kw in msg_lower for kw in ["not found in schema", "表", "table", "列", "column", "doesn't exist", "不存在"]):
            return "wrong_metric"

        if any(kw in msg_lower for kw in ["join", "关联", "on clause", "foreign key"]):
            return "wrong_join"

        if any(kw in msg_lower for kw in ["group by", "aggregat", "聚合"]):
            return "wrong_aggregation"

        # Dialect errors
        if any(kw in msg_lower for kw in ["syntax", "语法", "parse", "unexpected", "near"]):
            return "dialect_error"

        # Time range errors
        if any(kw in msg_lower for kw in ["date", "time", "日期", "时间", "timestamp"]):
            return "wrong_time_range"

        # Filter/member errors
        if any(kw in msg_lower for kw in ["filter", "where", "条件", "value", "值"]):
            return "missing_filter"

        # Semantic validation errors
        if any(kw in msg_lower for kw in ["semantic", "query ir", "missing intent", "缺失", "多余"]):
            return "semantic_mismatch"

        # Execution errors
        if any(kw in msg_lower for kw in ["timeout", "超时", "connection", "连接", "permission", "权限", "denied"]):
            return "execution_error"

        return "unknown"

    def fingerprint(self, error_message: str, sql: str | None = None) -> str:
        """Generate a fingerprint for deduplication."""
        content = f"{error_message[:200]}|{ (sql or '')[:200]}"
        return hashlib.md5(content.encode()).hexdigest()[:12]

    def make_fingerprint(self, error_message: str, sql: str | None = None) -> ErrorFingerprint:
        """Classify and fingerprint an error."""
        category = self.classify(error_message, sql)
        fp = self.fingerprint(error_message, sql)
        return ErrorFingerprint(
            category=category,
            fingerprint=fp,
            error_message=error_message[:500],
            sql_snippet=(sql or "")[:100],
            max_retries=2,
        )

    def repair_budget_exceeded(
        self,
        fingerprint: ErrorFingerprint,
        category_counts: dict[str, int],
        global_count: int,
    ) -> bool:
        """Check if repair budget is exceeded for this error."""
        # Per-fingerprint limit
        if fingerprint.retry_count >= fingerprint.max_retries:
            return True
        # Per-category limit (2 per category)
        if category_counts.get(fingerprint.category, 0) >= 2:
            return True
        # Global limit (4 total)
        if global_count >= 4:
            return True
        return False
