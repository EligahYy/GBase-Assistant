# backend/app/vector/grep_retriever.py
"""GrepRetriever: 基于 ripgrep 的知识文件精确检索 + QueryRouter 查询分流。"""

from __future__ import annotations

import asyncio
import json
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
MAX_MATCH_CONTEXT = 1200


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
                chunks = self._parse_json_events(output)
                all_chunks.extend(chunks)
            except FileNotFoundError:
                logger.warning("ripgrep (rg) 未安装或不在 PATH 中")
                return []
            except Exception as e:
                logger.warning("ripgrep 搜索失败 (keyword=%s): %s", kw, e)
                continue

        return self._rank_and_dedup(all_chunks, keywords)[:10]

    def _extract_keywords(self, query: str) -> list[str]:
        """从 query 中提取有区分度的关键词。"""
        tokens = re.split(r"[\s,，。！？：、；\(\)\[\]{}]+", query)
        direct_keywords: list[str] = []
        derived_keywords: list[str] = []
        for t in tokens:
            t = t.strip().strip("`\"'")
            if not t:
                continue
            if re.fullmatch(r"[\u4e00-\u9fff]+", t) and len(t) > 4:
                # 中文没有空格分词。优先搜索 4/3/2 字连续词组，避免把整句当成一个关键词。
                for size in (4, 3, 2):
                    for i in range(len(t) - size + 1):
                        part = t[i : i + size]
                        if part not in STOPWORDS:
                            derived_keywords.append(part)
            elif len(t) > 1 and t.lower() not in STOPWORDS:
                direct_keywords.append(t)
        keywords = direct_keywords + derived_keywords
        if not keywords:
            keywords.append(query.strip())
        return list(dict.fromkeys(keywords))

    async def _rg_search(self, pattern: str) -> list[dict]:
        """执行 ripgrep --json 搜索，返回 JSON 事件列表。"""
        args = ["rg", "--json", "-i", "-C", "2", "-m", "10"]
        for g in SEARCH_GLOBS:
            args.extend(["-g", g])
        args.append("--")
        args.append(pattern)
        args.append(str(self._dir))

        try:
            proc = await asyncio.wait_for(
                asyncio.create_subprocess_exec(
                    *args,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                ),
                timeout=10.0,
            )
        except TimeoutError:
            logger.warning("ripgrep 搜索超时 (pattern=%s)", pattern)
            return []

        stdout, stderr = await proc.communicate()

        if proc.returncode not in (0, 1):
            stderr_text = stderr.decode("utf-8", errors="replace")[:200] if stderr else ""
            logger.warning("ripgrep 异常退出 (exit=%d, pattern=%s): %s", proc.returncode, pattern, stderr_text)
            return []

        events = []
        for line in stdout.decode("utf-8", errors="replace").split("\n"):
            line = line.strip()
            if line:
                try:
                    events.append(json.loads(line))
                except json.JSONDecodeError:
                    continue
        return events

    def _parse_json_events(self, events: list[dict]) -> list[KnowledgeChunk]:
        """将 rg --json 事件列表解析为 KnowledgeChunk 列表。

        JSON 事件类型：begin（文件开始）、match（匹配行）、context（上下文行）、end（文件结束）。
        """
        chunks: list[KnowledgeChunk] = []
        current_file = ""
        current_lines: list[str] = []

        for ev in events:
            etype = ev.get("type", "")
            data = ev.get("data", {})
            path_info = data.get("path", {})
            file_path = path_info.get("text", "")
            lines_info = data.get("lines", {})

            if etype in ("begin", "end"):
                if etype == "begin" and file_path:
                    current_file = file_path
                    current_lines = []
                elif etype == "end" and current_file and current_lines:
                    chunks.append(self._build_chunk(current_file, current_lines))
                    current_file = ""
                    current_lines = []
            elif etype in ("match", "context"):
                if file_path and file_path != current_file:
                    if current_file and current_lines:
                        chunks.append(self._build_chunk(current_file, current_lines))
                    current_file = file_path
                    current_lines = []
                text = lines_info.get("text", "")
                if text:
                    if etype == "match" and len(text) > MAX_MATCH_CONTEXT:
                        raw = text.encode("utf-8")
                        for submatch in data.get("submatches", []):
                            # ripgrep reports byte offsets, not Python character offsets.
                            start = max(0, int(submatch.get("start", 0)) - MAX_MATCH_CONTEXT // 2)
                            end = min(len(raw), int(submatch.get("end", 0)) + MAX_MATCH_CONTEXT // 2)
                            excerpt = raw[start:end].decode("utf-8", errors="ignore")
                            excerpt = excerpt.replace("\\n", "\n").replace('\\"', '"')
                            current_lines.append(excerpt.rstrip("\n"))
                    elif len(text) <= MAX_MATCH_CONTEXT:
                        current_lines.append(text.rstrip("\n"))

        if current_file and current_lines:
            chunks.append(self._build_chunk(current_file, current_lines))

        return chunks

    def _build_chunk(self, file_path: str, lines: list[str]) -> KnowledgeChunk:
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
        return "general"

    def _rank_and_dedup(self, chunks: list[KnowledgeChunk], keywords: list[str]) -> list[KnowledgeChunk]:
        """按关键词相关度排序并去重，保留同一文档中的不同命中上下文。"""
        seen: set[str] = set()
        result: list[KnowledgeChunk] = []
        lowered_keywords = [keyword.lower() for keyword in keywords]

        def relevance(chunk: KnowledgeChunk) -> tuple[int, int]:
            content = chunk.content.lower()
            score = sum(len(keyword) ** 2 for keyword in lowered_keywords if keyword in content)
            return score, -len(chunk.content)

        for c in sorted(chunks, key=relevance, reverse=True):
            key = f"{c.source}|{' '.join(c.content.split())[:240]}"
            if key not in seen:
                seen.add(key)
                result.append(c)
        return result
