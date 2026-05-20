# 混合检索方案实现计划

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 实现 Qdrant 向量检索 + ripgrep 精确检索的混合方案，通过 QueryRouter 分流精确/语义查询，RRF 融合双路径结果。

**Architecture:** 新增 `grep_retriever.py`（QueryRouter + GrepRetriever）和 `hybrid_retriever.py`（HybridKnowledgeRetriever + RRF），修改 `dependencies.py` 的 `get_knowledge_retriever()` 接入混合检索器。chain 层和 api 层不变。

**Tech Stack:** Python 3.12+ asyncio, ripgrep CLI, Qdrant（已有）, pytest + pytest-asyncio

**Spec:** `docs/superpowers/specs/2026-05-20-hybrid-retrieval-design.md`

---

## 文件结构

```
backend/app/vector/
├── grep_retriever.py       # 新增: QueryRouter + GrepRetriever
├── hybrid_retriever.py     # 新增: HybridKnowledgeRetriever + RRF
├── retrievers.py           # 不变
├── client.py               # 不变
├── embedder.py             # 不变
└── ingest.py               # 不变

backend/app/
├── dependencies.py          # 修改: get_knowledge_retriever() 接入 Hybrid

backend/tests/
├── test_grep_retriever.py   # 新增
└── test_hybrid_retriever.py # 新增
```

各文件职责：
- `grep_retriever.py` — 查询分流规则 + ripgrep 知识文件搜索，独立可测
- `hybrid_retriever.py` — 混合检索编排（路由 + 双路径 + RRF 融合），实现 KnowledgeRetriever Protocol
- `dependencies.py` — 仅修改 `get_knowledge_retriever()` 的组装逻辑

---

### Task 1: QueryRouter — 查询分流

**Files:**
- Create: `backend/app/vector/grep_retriever.py`
- Test: `backend/tests/test_grep_retriever.py`

- [ ] **Step 1: 编写 QueryRouter 的失败测试**

```python
# backend/tests/test_grep_retriever.py
from __future__ import annotations

import pytest
from app.vector.grep_retriever import QueryRouter


class TestQueryRouter:
    def test_classifies_four_digit_error_code_as_precise(self):
        assert QueryRouter.classify("错误码 1040 是什么意思") == "precise"

    def test_classifies_error_code_with_label_as_precise(self):
        assert QueryRouter.classify("报错 1146 怎么解决") == "precise"

    def test_classifies_sql_keyword_as_precise(self):
        assert QueryRouter.classify("SELECT 语句怎么写") == "precise"
        assert QueryRouter.classify("CREATE TABLE 语法") == "precise"
        assert QueryRouter.classify("INSERT INTO 怎么用") == "precise"

    def test_classifies_backtick_identifier_as_precise(self):
        assert QueryRouter.classify("`max_allowed_packet` 参数") == "precise"

    def test_classifies_gbase_tool_as_precise(self):
        assert QueryRouter.classify("gccli 连接参数") == "precise"
        assert QueryRouter.classify("gcluster 是什么") == "precise"

    def test_classifies_param_query_as_precise(self):
        assert QueryRouter.classify("参数 max_connections 默认值") == "precise"
        assert QueryRouter.classify("配置项 wait_timeout 怎么调整") == "precise"

    def test_classifies_natural_language_as_semantic(self):
        assert QueryRouter.classify("GBase 8a 支持触发器吗") == "semantic"
        assert QueryRouter.classify("怎么优化查询性能") == "semantic"
        assert QueryRouter.classify("分布键应该怎么选") == "semantic"

    def test_classifies_english_question_as_semantic(self):
        assert QueryRouter.classify("how to optimize query performance") == "semantic"

    def test_empty_query_returns_semantic(self):
        assert QueryRouter.classify("") == "semantic"
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && TESTING=1 uv run pytest tests/test_grep_retriever.py::TestQueryRouter -v
```
Expected: 全部 FAIL（`ModuleNotFoundError` 或 `ImportError`）

- [ ] **Step 3: 实现 QueryRouter**

```python
# backend/app/vector/grep_retriever.py
"""GrepRetriever: 基于 ripgrep 的知识文件精确检索 + QueryRouter 查询分流。"""

from __future__ import annotations

import logging
import re
from typing import Literal

logger = logging.getLogger(__name__)

PRECISE_PATTERNS: list[tuple[str, str]] = [
    (r"(错误码|报错|error)\s*[:：]?\s*\d+", "labeled_error_code"),
    (r"\b\d{4}\b", "four_digit_code"),
    (r"\b(SELECT|INSERT|UPDATE|DELETE|CREATE|ALTER|DROP|GRANT|REVOKE)\b", "sql_keyword"),
    (r"`\w+`", "backtick_identifier"),
    (r"\b(gbase|gccli|gcluster)\b", "gbase_tool"),
    (r"(参数|配置项|变量)\s*[:：]?\s*\w+", "param_query"),
]


class QueryRouter:
    """规则驱动的查询分流：精确查询（错误码/SQL关键字/参数） vs 语义查询。"""

    @staticmethod
    def classify(query: str) -> Literal["precise", "semantic"]:
        if not query or not query.strip():
            return "semantic"
        for pattern, _name in PRECISE_PATTERNS:
            if re.search(pattern, query, re.IGNORECASE):
                return "precise"
        return "semantic"
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && TESTING=1 uv run pytest tests/test_grep_retriever.py::TestQueryRouter -v
```
Expected: 9 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/vector/grep_retriever.py backend/tests/test_grep_retriever.py
git commit -m "feat: add QueryRouter for precise vs semantic query classification"
```

---

### Task 2: GrepRetriever — ripgrep 知识文件搜索

**Files:**
- Modify: `backend/app/vector/grep_retriever.py`（追加类）
- Modify: `backend/tests/test_grep_retriever.py`（追加测试）

- [ ] **Step 1: 编写 GrepRetriever 的失败测试**

```python
# 追加到 backend/tests/test_grep_retriever.py

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

from app.protocols import KnowledgeChunk


class TestGrepRetriever:
    @pytest.fixture
    def knowledge_dir(self):
        return Path(__file__).parent.parent.parent / "knowledge"

    @pytest.mark.anyio
    async def test_retrieve_finds_error_code(self, knowledge_dir):
        from app.vector.grep_retriever import GrepRetriever

        retriever = GrepRetriever(knowledge_dir)
        results = await retriever.retrieve("错误码 1040")

        assert len(results) > 0
        assert any("1040" in r.content for r in results)

    @pytest.mark.anyio
    async def test_retrieve_finds_sql_keyword(self, knowledge_dir):
        from app.vector.grep_retriever import GrepRetriever

        retriever = GrepRetriever(knowledge_dir)
        results = await retriever.retrieve("SELECT")

        assert len(results) > 0

    @pytest.mark.anyio
    async def test_retrieve_returns_knowledge_chunks(self, knowledge_dir):
        from app.vector.grep_retriever import GrepRetriever

        retriever = GrepRetriever(knowledge_dir)
        results = await retriever.retrieve("GBase 8a")

        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, KnowledgeChunk)
            assert r.content
            assert r.source

    @pytest.mark.anyio
    async def test_empty_query_returns_empty(self, knowledge_dir):
        from app.vector.grep_retriever import GrepRetriever

        retriever = GrepRetriever(knowledge_dir)
        results = await retriever.retrieve("")

        assert results == []

    @pytest.mark.anyio
    async def test_rg_not_found_graceful_degradation(self, knowledge_dir):
        """ripgrep 不可用时优雅降级，返回空列表不抛异常。"""
        from app.vector.grep_retriever import GrepRetriever

        retriever = GrepRetriever(knowledge_dir)
        with patch("asyncio.create_subprocess_exec", side_effect=FileNotFoundError):
            results = await retriever.retrieve("1040")

        assert results == []

    @pytest.mark.anyio
    async def test_rg_nonzero_exit_graceful(self, knowledge_dir):
        """ripgrep 返回非零退出码（无匹配）时返回空列表。"""
        from app.vector.grep_retriever import GrepRetriever

        retriever = GrepRetriever(knowledge_dir)
        mock_proc = AsyncMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(return_value=(b"", b""))
        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            results = await retriever.retrieve("nonexistent_xyz_123")

        assert results == []
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && TESTING=1 uv run pytest tests/test_grep_retriever.py::TestGrepRetriever -v
```
Expected: FAIL（`ImportError: cannot import name 'GrepRetriever'`）

- [ ] **Step 3: 实现 GrepRetriever**

```python
# 追加到 backend/app/vector/grep_retriever.py（QueryRouter 之后）

import asyncio
from pathlib import Path

from app.protocols import KnowledgeChunk

# 停用词：中文和英文常见无意义词
STOPWORDS = frozenset({
    "的", "了", "在", "是", "我", "有", "和", "就", "不", "人", "都", "一",
    "一个", "上", "也", "很", "到", "说", "要", "去", "你", "会", "着",
    "没有", "看", "好", "自己", "这", "他", "她", "它", "们", "那", "些",
    "什么", "怎么", "怎样", "如何", "为什么", "可以", "能", "应该", "需要",
    "用", "做", "做", "让", "被", "把", "从", "对", "向", "与", "或",
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
        return list(dict.fromkeys(keywords))  # 去重保序

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

            # 匹配行格式: path:linenum:text
            # 上下文行格式: path-linenum-text
            if ":" in line:
                parts = line.split(":", 2)
                if len(parts) >= 3 and parts[1].strip().isdigit():
                    current_file = parts[0]
                    current_lines.append(parts[2])
                elif "-" in line:
                    # 上下文行
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
        content = "\n".join(lines[:6])  # 最多保留 6 行
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
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && TESTING=1 uv run pytest tests/test_grep_retriever.py::TestGrepRetriever -v
```
Expected: 6 PASS

- [ ] **Step 5: 运行全部测试确认无回归**

```bash
cd backend && TESTING=1 uv run pytest tests/test_grep_retriever.py -v
```
Expected: 15 PASS（9 个 QueryRouter + 6 个 GrepRetriever）

- [ ] **Step 6: 提交**

```bash
git add backend/app/vector/grep_retriever.py backend/tests/test_grep_retriever.py
git commit -m "feat: add GrepRetriever — ripgrep-based knowledge file search"
```

---

### Task 3: HybridKnowledgeRetriever + RRF 融合

**Files:**
- Create: `backend/app/vector/hybrid_retriever.py`
- Test: `backend/tests/test_hybrid_retriever.py`

- [ ] **Step 1: 编写 HybridKnowledgeRetriever 的失败测试**

```python
# backend/tests/test_hybrid_retriever.py
from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.protocols import KnowledgeChunk, KnowledgeRetriever


class FakeKnowledgeRetriever:
    """可控的 KnowledgeRetriever 桩。"""

    def __init__(self, results: list[KnowledgeChunk] | None = None, should_fail: bool = False):
        self.results = results or []
        self.should_fail = should_fail
        self.retrieve_calls: list[tuple] = []

    async def retrieve(self, query: str, category: str | None = None) -> list[KnowledgeChunk]:
        self.retrieve_calls.append((query, category))
        if self.should_fail:
            raise RuntimeError("simulated failure")
        return self.results


def make_chunk(content: str, source: str = "", category: str = "") -> KnowledgeChunk:
    return KnowledgeChunk(content=content, source=source, category=category)


class TestHybridKnowledgeRetriever:
    @pytest.mark.anyio
    async def test_precise_query_uses_grep_first(self):
        """精确查询走 GrepRetriever 优先路径。"""
        from app.vector.hybrid_retriever import HybridKnowledgeRetriever

        grep_results = [make_chunk("1040: 连接数已达上限", "error_codes.json", "error_code")]
        grep = FakeKnowledgeRetriever(results=grep_results)
        vector = FakeKnowledgeRetriever(results=[])

        hybrid = HybridKnowledgeRetriever(vector=vector, grep=grep)
        results = await hybrid.retrieve("错误码 1040")

        assert len(grep.retrieve_calls) == 1
        assert len(results) == 1
        assert "1040" in results[0].content

    @pytest.mark.anyio
    async def test_semantic_query_uses_vector_first(self):
        """语义查询走 Qdrant 优先路径。"""
        from app.vector.hybrid_retriever import HybridKnowledgeRetriever

        vector_results = [make_chunk("GBase 8a 不支持触发器", "faq.json", "faq")]
        vector = FakeKnowledgeRetriever(results=vector_results)
        grep = FakeKnowledgeRetriever(results=[])

        hybrid = HybridKnowledgeRetriever(vector=vector, grep=grep)
        results = await hybrid.retrieve("GBase 8a 支持触发器吗")

        assert len(vector.retrieve_calls) == 1
        assert len(results) == 1
        assert "触发器" in results[0].content

    @pytest.mark.anyio
    async def test_precise_falls_back_to_vector_when_grep_empty(self):
        """精确查询：grep 空结果时降级到 Qdrant。"""
        from app.vector.hybrid_retriever import HybridKnowledgeRetriever

        grep = FakeKnowledgeRetriever(results=[])
        vector = FakeKnowledgeRetriever(
            results=[make_chunk("关于连接数的说明", "faq.json", "faq")]
        )

        hybrid = HybridKnowledgeRetriever(vector=vector, grep=grep)
        results = await hybrid.retrieve("错误码 1040")

        assert len(grep.retrieve_calls) == 1
        assert len(vector.retrieve_calls) == 1
        assert len(results) == 1

    @pytest.mark.anyio
    async def test_semantic_falls_back_to_grep_when_vector_empty(self):
        """语义查询：Qdrant 空结果时降级到 grep。"""
        from app.vector.hybrid_retriever import HybridKnowledgeRetriever

        vector = FakeKnowledgeRetriever(results=[])
        grep = FakeKnowledgeRetriever(
            results=[make_chunk("触发器相关文档", "faq.json", "faq")]
        )

        hybrid = HybridKnowledgeRetriever(vector=vector, grep=grep)
        results = await hybrid.retrieve("GBase 8a 支持触发器吗")

        assert len(vector.retrieve_calls) == 1
        assert len(grep.retrieve_calls) == 1
        assert len(results) == 1

    @pytest.mark.anyio
    async def test_rrf_fusion_merges_both_paths(self):
        """双路径均非空时，RRF 融合去重。"""
        from app.vector.hybrid_retriever import HybridKnowledgeRetriever

        vector = FakeKnowledgeRetriever(
            results=[
                make_chunk("chunk A", "faq.json", "faq"),
                make_chunk("chunk B", "error_codes.json", "error_code"),
            ]
        )
        grep = FakeKnowledgeRetriever(
            results=[
                make_chunk("chunk B dup", "error_codes.json", "error_code"),
                make_chunk("chunk C", "ops_cluster.json", "ops"),
            ]
        )

        hybrid = HybridKnowledgeRetriever(vector=vector, grep=grep)
        results = await hybrid.retrieve("GBase 8a 错误码")

        # RRF 按 source 去重，error_codes.json 只出现一次
        sources = [r.source for r in results]
        assert len(sources) == len(set(sources))
        assert len(results) == 3

    @pytest.mark.anyio
    async def test_grep_failure_falls_back_to_vector(self):
        """Grep 异常时降级到 Qdrant。"""
        from app.vector.hybrid_retriever import HybridKnowledgeRetriever

        grep = FakeKnowledgeRetriever(should_fail=True)
        vector = FakeKnowledgeRetriever(
            results=[make_chunk("fallback content", "faq.json", "faq")]
        )

        hybrid = HybridKnowledgeRetriever(vector=vector, grep=grep)
        results = await hybrid.retrieve("错误码 1040")

        assert len(results) == 1
        assert results[0].content == "fallback content"

    @pytest.mark.anyio
    async def test_implements_knowledge_retriever_protocol(self):
        """HybridKnowledgeRetriever 实现 KnowledgeRetriever Protocol。"""
        from app.vector.hybrid_retriever import HybridKnowledgeRetriever

        vector = FakeKnowledgeRetriever()
        grep = FakeKnowledgeRetriever()
        hybrid = HybridKnowledgeRetriever(vector=vector, grep=grep)

        assert isinstance(hybrid, KnowledgeRetriever)
```

- [ ] **Step 2: 运行测试确认失败**

```bash
cd backend && TESTING=1 uv run pytest tests/test_hybrid_retriever.py -v
```
Expected: FAIL（`ModuleNotFoundError`）

- [ ] **Step 3: 实现 HybridKnowledgeRetriever + RRF**

```python
# backend/app/vector/hybrid_retriever.py
"""HybridKnowledgeRetriever: Qdrant 向量检索 + ripgrep 精确检索 混合编排。"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.protocols import KnowledgeChunk, KnowledgeRetriever

if TYPE_CHECKING:
    from app.vector.grep_retriever import QueryRouter

logger = logging.getLogger(__name__)

RRF_K = 60
TOP_K = 5


def reciprocal_rank_fusion(
    results_a: list[KnowledgeChunk],
    results_b: list[KnowledgeChunk],
    k: int = RRF_K,
    top_k: int = TOP_K,
) -> list[KnowledgeChunk]:
    """Reciprocal Rank Fusion：基于排名的倒数加权融合两个排序列表。

    score(d) = Σ 1/(k + rank_i(d))
    """
    scores: dict[str, float] = {}
    content_map: dict[str, KnowledgeChunk] = {}

    for rank, chunk in enumerate(results_a, 1):
        key = chunk.source or chunk.content[:80]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        content_map[key] = chunk

    for rank, chunk in enumerate(results_b, 1):
        key = chunk.source or chunk.content[:80]
        scores[key] = scores.get(key, 0.0) + 1.0 / (k + rank)
        if key not in content_map:
            content_map[key] = chunk

    sorted_keys = sorted(scores, key=lambda kk: scores[kk], reverse=True)
    return [content_map[key] for key in sorted_keys[:top_k]]


class HybridKnowledgeRetriever:
    """混合知识检索器：按查询类型分流到向量或 grep 路径，互补兜底。

    实现 KnowledgeRetriever Protocol，对 chain 层透明。
    """

    def __init__(
        self,
        vector: KnowledgeRetriever | None,
        grep: KnowledgeRetriever | None,
        router: QueryRouter | None = None,
    ) -> None:
        self._vector = vector
        self._grep = grep
        if router is None:
            from app.vector.grep_retriever import QueryRouter as QR

            router = QR()
        self._router = router

    async def retrieve(self, query: str, category: str | None = None) -> list[KnowledgeChunk]:
        qtype = self._router.classify(query)

        if qtype == "precise":
            primary_results = await self._safe_retrieve(self._grep, query, category)
            if primary_results:
                logger.debug("precise 查询走 GrepRetriever，命中 %d 条", len(primary_results))
                return primary_results[:TOP_K]
            fallback_results = await self._safe_retrieve(self._vector, query, category)
            if fallback_results:
                logger.debug("precise 查询 GrepRetriever 未命中，降级到 Qdrant，命中 %d 条", len(fallback_results))
            return fallback_results[:TOP_K]
        else:
            vector_results = await self._safe_retrieve(self._vector, query, category)
            grep_results = await self._safe_retrieve(self._grep, query, category)

            if vector_results and grep_results:
                logger.debug("semantic 查询双路径均有结果，RRF 融合")
                return reciprocal_rank_fusion(vector_results, grep_results)
            elif vector_results:
                logger.debug("semantic 查询走 Qdrant，命中 %d 条", len(vector_results))
                return vector_results[:TOP_K]
            elif grep_results:
                logger.debug("semantic 查询 Qdrant 未命中，降级到 GrepRetriever，命中 %d 条", len(grep_results))
                return grep_results[:TOP_K]
            return []

    async def _safe_retrieve(
        self,
        retriever: KnowledgeRetriever | None,
        query: str,
        category: str | None,
    ) -> list[KnowledgeChunk]:
        if retriever is None:
            return []
        try:
            return await retriever.retrieve(query, category)
        except Exception as e:
            logger.warning("检索器异常: %s", e)
            return []
```

- [ ] **Step 4: 运行测试确认通过**

```bash
cd backend && TESTING=1 uv run pytest tests/test_hybrid_retriever.py -v
```
Expected: 7 PASS

- [ ] **Step 5: 提交**

```bash
git add backend/app/vector/hybrid_retriever.py backend/tests/test_hybrid_retriever.py
git commit -m "feat: add HybridKnowledgeRetriever with RRF fusion"
```

---

### Task 4: 集成到 dependencies.py

**Files:**
- Modify: `backend/app/dependencies.py`
- Modify: `backend/tests/test_dependencies.py`（更新测试）

- [ ] **Step 1: 修改 get_knowledge_retriever()**

```python
# 修改 backend/app/dependencies.py 中的 get_knowledge_retriever()

def get_knowledge_retriever() -> KnowledgeRetriever:
    """KnowledgeRetriever：混合检索（Qdrant + ripgrep），双路径互补兜底。"""
    from app.vector.client import is_qdrant_available

    # 构建 Qdrant 检索器（可选）
    vector = None
    if is_qdrant_available():
        try:
            from app.vector.retrievers import QdrantKnowledgeRetriever
            vector = QdrantKnowledgeRetriever()
        except Exception as e:
            logger.debug("QdrantKnowledgeRetriever 实例化失败: %s", e)

    # 构建 Grep 检索器
    from app.config import get_settings
    from app.vector.grep_retriever import GrepRetriever

    grep = GrepRetriever(get_settings().knowledge_dir)

    # 混合检索器（内部分流 + 互补兜底）
    from app.vector.hybrid_retriever import HybridKnowledgeRetriever

    hybrid = HybridKnowledgeRetriever(vector=vector, grep=grep)

    # 最外层兜底：Hybrid 整体失败时回退到 FileKnowledgeRetriever
    return FallbackRetriever(
        primary=hybrid,
        fallback=_get_file_knowledge_retriever(),
        name="KnowledgeRetriever",
    )  # type: ignore[return-value]
```

- [ ] **Step 2: 更新 dependencies 测试**

```python
# 在 backend/tests/test_dependencies.py 中替换 TestKnowledgeRetrieverFallback 的三个测试：

class TestKnowledgeRetrieverFallback:
    def test_returns_hybrid_when_qdrant_unavailable(self):
        """Qdrant 不可用时应返回混合检索器（grep-only 但非裸 FileKnowledgeRetriever）。"""
        retriever = get_knowledge_retriever()
        assert retriever is not None
        # 测试环境无 Qdrant，应返回 FallbackRetriever 包裹 Hybrid
        assert isinstance(retriever, FallbackRetriever)

    def test_returns_wrapper_when_qdrant_available(self):
        with patch("app.vector.client.is_qdrant_available", return_value=True):
            retriever = get_knowledge_retriever()
            assert retriever is not None
            assert isinstance(retriever, FallbackRetriever)

    @pytest.mark.anyio
    async def test_fallback_returns_results(self):
        """混合检索器的最终兜底：应能返回知识检索结果。"""
        retriever = get_knowledge_retriever()
        result = await retriever.retrieve("1040")
        assert isinstance(result, list)
        # 无论是向量命中还是 grep 命中，只要返回 list 即正确
```

- [ ] **Step 3: 运行全部依赖注入测试**

```bash
cd backend && TESTING=1 uv run pytest tests/test_dependencies.py -v
```
Expected: 全部 PASS

- [ ] **Step 4: 运行全部测试确认无回归**

```bash
cd backend && TESTING=1 uv run pytest -v
```
Expected: 全部通过（约 80+ 用例 + 新增约 22 个 = 100+ 用例）

- [ ] **Step 5: 提交**

```bash
git add backend/app/dependencies.py backend/tests/test_dependencies.py
git commit -m "feat: integrate HybridKnowledgeRetriever into dependencies"
```

---

## 验证清单

实现全部完成后，逐项验证：

1. **TESTING=1 全量测试通过**：`cd backend && TESTING=1 uv run pytest -v`
2. **GrepRetriever 真实搜索可用**：在项目根目录执行 `rg -i "1040" knowledge/`，确认有输出
3. **Hybrid 无 Qdrant 降级正常**：不启动 Qdrant，后端应正常启动，知识问答走 grep 路径
4. **Hybrid 有 Qdrant 融合正常**：启动 Qdrant，查询应走完整混合路径
