# backend/tests/test_grep_retriever.py
from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.protocols import KnowledgeChunk
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

    def test_bare_four_digit_code_as_precise(self):
        assert QueryRouter.classify("1040") == "precise"

    def test_whitespace_only_query_returns_semantic(self):
        assert QueryRouter.classify("   ") == "semantic"

    def test_empty_query_returns_semantic(self):
        assert QueryRouter.classify("") == "semantic"


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
    async def test_random_distribution_question_prioritizes_create_table_context(self, knowledge_dir):
        from app.agents.graph import _expand_knowledge_query
        from app.vector.grep_retriever import GrepRetriever

        query = _expand_knowledge_query("如何创建随机分布表？")
        results = await GrepRetriever(knowledge_dir).retrieve(query)

        assert results
        assert "默认为随机分布表" in results[0].content[:3000]

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

    def test_extracts_meaningful_chinese_ngrams(self, tmp_path):
        from app.vector.grep_retriever import GrepRetriever

        retriever = GrepRetriever(tmp_path)

        assert "随机分布" in retriever._extract_keywords("如何创建随机分布表？")[:5]

    @pytest.mark.anyio
    async def test_large_pdf_cache_returns_match_context_not_entire_json(self, tmp_path):
        from app.vector.grep_retriever import GrepRetriever

        content = "前置内容" * 400 + "随机分布表通过 CREATE TABLE 创建。" + "后置内容" * 400
        (tmp_path / "manual.pages.json").write_text(
            json.dumps({"100": content}, ensure_ascii=False),
            encoding="utf-8",
        )

        results = await GrepRetriever(tmp_path).retrieve("如何创建随机分布表？")

        assert results
        assert any("随机分布表" in result.content for result in results)
        assert all(len(result.content) < len(content) for result in results)
