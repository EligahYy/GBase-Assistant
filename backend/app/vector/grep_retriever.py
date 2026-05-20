# backend/app/vector/grep_retriever.py
"""GrepRetriever: 基于 ripgrep 的知识文件精确检索 + QueryRouter 查询分流。"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Literal

from app.protocols import KnowledgeChunk

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


# ── 停用词：中文和英文常见无意义词 ──
STOPWORDS = frozenset({
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
    "什么", "怎么", "怎样", "如何", "为什么", "可以", "能", "应该", "需要",
    "用", "做", "让", "被", "把", "从", "对", "向", "与", "或",
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "have", "has", "had", "do", "does", "did", "will", "would", "could",
    "should", "may", "might", "can", "shall", "to", "of", "in", "for",
    "on", "with", "at", "by", "from", "as", "into", "through", "during",
    "before", "after", "above", "below", "between", "under", "again",
    "further", "then", "once", "here", "there", "when", "where", "why",
    "how", "all", "both", "each", "few", "more", "most", "other", "some",
    "such", "only", "own", "same", "so", "than", "too", "very", "just",
    "don", "now", "and", "but", "or", "not", "this", "that", "it", "its",
})

SEARCH_GLOBS = ["*.md", "*.yaml", "*.json", "*.jsonl"]


class GrepRetriever:
    """基于 ripgrep 的知识文件精确检索器。

    调用 ripgrep CLI 在 knowledge/ 目录中全文搜索，
    将匹配的段落封装为 KnowledgeChunk 返回。
    """

    def __init__(self, knowledge_dir: Path) -> None:
        self._dir = knowledge_dir

    async def retrieve(self, query: str, category: str | None = None) -> list[KnowledgeChunk]:
        if not query or not query.strip():
            return []

        keywords = self._extract_keywords(query)
        if not keywords:
            return []

        all_chunks: list[KnowledgeChunk] = []
        for kw in keywords[:5]:
            try:
                output = await self._rg_search(kw)
                chunks = self._parse_rg_output(output, kw)
                all_chunks.extend(chunks)
            except FileNotFoundError:
                logger.warning("ripgrep (rg) 未安装或不在 PATH 中")
                return []
            except Exception as e:
                logger.warning("ripgrep 搜索失败 (keyword=%s): %s", kw, e)
                continue

        return self._dedup_by_source(all_chunks)[:10]

    def _extract_keywords(self, query: str) -> list[str]:
        """从 query 中提取有区分度的关键词。"""
        tokens = re.split(r"[\s,，。！？：、；\(\)\[\]{}]+", query)
        keywords = []
        for t in tokens:
            t = t.strip().strip("`\"'")
            if len(t) > 1 and t.lower() not in STOPWORDS:
                keywords.append(t)
        if not keywords:
            keywords.append(query.strip())
        return list(dict.fromkeys(keywords))

    async def _rg_search(self, pattern: str) -> str:
        """执行 ripgrep 搜索，返回 stdout 字符串。"""
        args = ["rg", "-i", "-n", "-C", "2", "-m", "10"]
        for g in SEARCH_GLOBS:
            args.extend(["-g", g])
        args.append("--")
        args.append(pattern)
        args.append(str(self._dir))

        proc = await asyncio.create_subprocess_exec(
            *args,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await proc.communicate()
        return stdout.decode("utf-8", errors="replace")

    def _parse_rg_output(self, output: str, keyword: str) -> list[KnowledgeChunk]:
        """解析 ripgrep 输出为 KnowledgeChunk 列表。

        ripgrep -C 2 输出格式：
        filepath:linenum:content  (匹配行)
        filepath-linenum-content  (上下文行)
        -- (文件分隔符)
        """
        chunks: list[KnowledgeChunk] = []
        current_file = ""
        current_lines: list[str] = []

        for line in output.split("\n"):
            if line == "--":
                if current_file and current_lines:
                    chunks.append(self._build_chunk(current_file, current_lines, keyword))
                current_file = ""
                current_lines = []
                continue
            if not line.strip():
                continue

            if ":" in line:
                parts = line.split(":", 2)
                if len(parts) >= 3 and parts[1].strip().isdigit():
                    current_file = parts[0]
                    current_lines.append(parts[2])
                elif "-" in line:
                    parts = line.split("-", 2)
                    if len(parts) >= 3 and parts[1].strip().isdigit():
                        current_lines.append(parts[2])
            elif current_lines:
                current_lines.append(line)

        if current_file and current_lines:
            chunks.append(self._build_chunk(current_file, current_lines, keyword))

        return chunks

    def _build_chunk(self, file_path: str, lines: list[str], keyword: str) -> KnowledgeChunk:
        source = self._relative_source(file_path)
        content = "\n".join(lines[:6])
        category = self._infer_category(file_path)
        return KnowledgeChunk(content=content, source=source, category=category)

    def _relative_source(self, file_path: str) -> str:
        try:
            return str(Path(file_path).relative_to(self._dir))
        except ValueError:
            return file_path

    def _infer_category(self, file_path: str) -> str:
        if "error_codes" in file_path:
            return "error_code"
        if "faq" in file_path:
            return "faq"
        if "dialect_rules" in file_path:
            return "dialect"
        if "ops_" in file_path:
            return "ops"
        if "sql_examples" in file_path:
            return "example"
        return "general"

    def _dedup_by_source(self, chunks: list[KnowledgeChunk]) -> list[KnowledgeChunk]:
        """按 source 去重，保留首次出现的 chunk，按匹配行数降序排列。"""
        seen: set[str] = set()
        result: list[KnowledgeChunk] = []
        for c in sorted(chunks, key=lambda c: len(c.content.split("\n")), reverse=True):
            key = c.source
            if key not in seen:
                seen.add(key)
                result.append(c)
        return result
