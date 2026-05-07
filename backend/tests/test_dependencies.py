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
from app.knowledge.loader import DbSchemaRetriever, FileExampleRetriever, FileKnowledgeRetriever
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
    def test_returns_file_retriever_when_qdrant_unavailable(self):
        """Qdrant 不可用时直接返回 FileKnowledgeRetriever。"""
        retriever = get_knowledge_retriever()
        assert retriever is not None
        assert isinstance(retriever, FileKnowledgeRetriever)

    def test_returns_wrapper_when_qdrant_available(self):
        with patch("app.vector.client.is_qdrant_available", return_value=True):
            retriever = get_knowledge_retriever()
            assert retriever is not None
            assert not isinstance(retriever, FileKnowledgeRetriever)
            assert isinstance(retriever, FallbackRetriever)

    @pytest.mark.anyio
    async def test_fallback_returns_file_knowledge(self):
        """Qdrant 失败后回退到 FileKnowledgeRetriever。"""
        fallback = FileKnowledgeRetriever()
        wrapper = FallbackRetriever(primary=None, fallback=fallback, name="KnowledgeRetriever")
        result = await wrapper.retrieve("GBase 8a 支持触发器吗")
        assert isinstance(result, list)


class TestLLMClient:
    def test_returns_lite_llm_impl(self):
        client = get_llm_client()
        assert isinstance(client, LiteLLMClientImpl)

    def test_model_override(self):
        client = get_llm_client(model="openai/gpt-4o")
        assert isinstance(client, LiteLLMClientImpl)
