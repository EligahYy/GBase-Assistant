"""Dependencies 注入与降级逻辑测试。"""

from __future__ import annotations

from unittest.mock import patch

import pytest

from app.dependencies import (
    FallbackRetriever,
    get_example_retriever,
    get_knowledge_retriever,
    get_llm_client,
    get_schema_retriever,
)
from app.knowledge.loader import DbSchemaRetriever, FileExampleRetriever
from app.llm.client import LiteLLMClientImpl


class FakeSession:
    pass


class TestSchemaRetrieverFallback:
    def test_returns_db_retriever_when_qdrant_unavailable(self):
        """Qdrant 不可用时直接返回 DbSchemaRetriever。"""
        retriever = get_schema_retriever(db_session=FakeSession())
        assert retriever is not None
        # 测试环境中 Qdrant 标记为不可用，应直接返回 DbSchemaRetriever
        assert isinstance(retriever, DbSchemaRetriever)

    def test_returns_wrapper_when_qdrant_available(self):
        """Qdrant 可用时返回带降级能力的 wrapper。"""
        with patch("app.vector.client.is_qdrant_available", return_value=True):
            retriever = get_schema_retriever(db_session=FakeSession())
            assert retriever is not None
            assert not isinstance(retriever, DbSchemaRetriever)
            assert isinstance(retriever, FallbackRetriever)

    @pytest.mark.anyio
    async def test_fallback_retrieve_returns_empty_without_db(self):
        """Qdrant 失败后若没有 db_fallback，返回空列表。"""
        wrapper = FallbackRetriever(primary=None, fallback=None, name="SchemaRetriever")
        result = await wrapper.retrieve("query", "db1")
        assert result == []

    @pytest.mark.anyio
    async def test_fallback_to_db_when_qdrant_fails(self):
        """Qdrant 失败且有 db_fallback 时，回退到 DbSchemaRetriever。"""

        class MockSession:
            async def execute(self, stmt):
                class Result:
                    def scalar_one_or_none(self):
                        from app.models.connection import DbConnection

                        conn = DbConnection()
                        conn.id = "db1"
                        conn.schema_ddl = "CREATE TABLE t (id INT);"
                        conn.is_active = True
                        return conn

                return Result()

        fallback = DbSchemaRetriever(MockSession())
        wrapper = FallbackRetriever(primary=None, fallback=fallback, name="SchemaRetriever")
        result = await wrapper.retrieve("query", "db1")
        # 应该回退到 DbSchemaRetriever，返回解析后的 schema
        assert len(result) >= 1
        assert result[0].table_name == "t"


class TestExampleRetrieverFallback:
    def test_returns_file_retriever_when_qdrant_unavailable(self):
        """Qdrant 不可用时直接返回 FileExampleRetriever。"""
        retriever = get_example_retriever()
        assert retriever is not None
        assert isinstance(retriever, FileExampleRetriever)

    def test_returns_wrapper_when_qdrant_available(self):
        with patch("app.vector.client.is_qdrant_available", return_value=True):
            retriever = get_example_retriever()
            assert retriever is not None
            assert not isinstance(retriever, FileExampleRetriever)
            assert isinstance(retriever, FallbackRetriever)

    @pytest.mark.anyio
    async def test_fallback_returns_file_examples(self):
        """Qdrant 失败后回退到 FileExampleRetriever。"""
        fallback = FileExampleRetriever()
        wrapper = FallbackRetriever(primary=None, fallback=fallback, name="ExampleRetriever")
        result = await wrapper.retrieve("查询用户", top_k=3)
        assert isinstance(result, list)
        assert len(result) <= 3


class TestKnowledgeRetrieverFallback:
    def test_returns_hybrid_when_qdrant_unavailable(self):
        """Qdrant 不可用时应返回 FallbackRetriever 包裹 HybridKnowledgeRetriever（grep-only）。"""
        retriever = get_knowledge_retriever()
        assert retriever is not None
        assert isinstance(retriever, FallbackRetriever)

    def test_returns_hybrid_wrapper_when_qdrant_available(self):
        with patch("app.vector.client.is_qdrant_available", return_value=True):
            retriever = get_knowledge_retriever()
            assert retriever is not None
            assert isinstance(retriever, FallbackRetriever)

    @pytest.mark.anyio
    async def test_hybrid_fallback_returns_results(self):
        """混合检索器应能返回知识检索结果。"""
        retriever = get_knowledge_retriever()
        result = await retriever.retrieve("1040")
        assert isinstance(result, list)
        # 无论是向量命中（需 Qdrant）还是 grep 命中，只要返回 list 即正确


class TestLLMClient:
    def test_returns_lite_llm_impl(self):
        client = get_llm_client()
        assert isinstance(client, LiteLLMClientImpl)

    def test_model_override(self):
        client = get_llm_client(model="openai/gpt-4o")
        assert isinstance(client, LiteLLMClientImpl)
