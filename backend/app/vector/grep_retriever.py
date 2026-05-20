# backend/app/vector/grep_retriever.py
"""GrepRetriever: 基于 ripgrep 的知识文件精确检索 + QueryRouter 查询分流。"""

from __future__ import annotations

import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)

PRECISE_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)(错误码|报错|error)\s*[:：]?\s*\d+", "labeled_error_code"),
    (r"\b\d{4}\b", "four_digit_code"),
    (r"(?i)\b(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|GRANT|REVOKE)\b", "sql_keyword"),
    (r"(?i)`\w+`", "backtick_identifier"),
    (r"\b(gbase|gccli|gcluster)\b", "gbase_tool"),
    (r"(?i)(参数|配置项|变量)\s*[:：]?\s*\w+", "param_query"),
]


class QueryRouter:
    """规则驱动的查询分流：精确查询（错误码/SQL关键字/参数） vs 语义查询。"""

    @staticmethod
    def classify(query: str) -> Literal["precise", "semantic"]:
        """基于正则模式将查询分流为 precise（精确匹配）或 semantic（语义检索）。"""
        if not query or not query.strip():
            return "semantic"
        for pattern, _name in PRECISE_PATTERNS:
            if re.search(pattern, query):
                return "precise"
        return "semantic"
