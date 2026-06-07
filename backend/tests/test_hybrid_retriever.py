# backend/tests/test_hybrid_retriever.py
from __future__ import annotations

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
                make_chunk("chunk B", "error_codes.json", "error_code"),
                make_chunk("chunk C", "ops_cluster.json", "ops"),
            ]
        )

        hybrid = HybridKnowledgeRetriever(vector=vector, grep=grep)
        results = await hybrid.retrieve("GBase 8a 错误码")

        assert len(results) == 3

    def test_rrf_keeps_distinct_chapters_from_same_document(self):
        """同一 PDF 的不同章节不能因 source 相同而互相覆盖。"""
        from app.vector.hybrid_retriever import reciprocal_rank_fusion

        results = reciprocal_rank_fusion(
            [make_chunk("随机分布表创建语法", "GBase 8a 产品手册")],
            [make_chunk("哈希分布表创建语法", "GBase 8a 产品手册")],
        )

        assert [chunk.content for chunk in results] == ["随机分布表创建语法", "哈希分布表创建语法"]

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
