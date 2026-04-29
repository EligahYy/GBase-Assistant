"""Dependencies 注入与降级逻辑测试。"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.dependencies import (
    _QdrantExampleRetrieverWithFallback,
    _QdrantKnowledgeRetrieverWithFallback,
    _QdrantSchemaRetrieverWithFallback,
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
    def test_returns_qdrant_wrapper_when_db_session_provided(self):
        retriever = get_schema_retriever(db_session=FakeSession())
        assert retriever is not None
        assert not isinstance(retriever, DbSchemaRetriever)

    @pytest.mark.anyio
    async def test_fallback_retrieve_returns_empty_without_db(self):
        """Qdrant 失败后若没有 db_fallback，返回空列表。"""
        wrapper = _QdrantSchemaRetrieverWithFallback(db_session=None)
        with patch("app.vector.retrievers.get_qdrant_manager") as mock_mgr:
            mock_client = MagicMock()
            mock_client.search = AsyncMock(side_effect=Exception("qdrant down"))
            mock_mgr.return_value.client = mock_client

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

        wrapper = _QdrantSchemaRetrieverWithFallback(db_session=MockSession())
        with patch("app.vector.retrievers.get_qdrant_manager") as mock_mgr:
            mock_client = MagicMock()
            mock_client.search = AsyncMock(side_effect=Exception("qdrant down"))
            mock_mgr.return_value.client = mock_client

            result = await wrapper.retrieve("query", "db1")
            # 应该回退到 DbSchemaRetriever，返回解析后的 schema
            assert len(result) >= 1
            assert result[0].table_name == "t"


class TestExampleRetrieverFallback:
    def test_returns_qdrant_wrapper(self):
        retriever = get_example_retriever()
        assert retriever is not None
        assert not isinstance(retriever, FileExampleRetriever)

    @pytest.mark.anyio
    async def test_fallback_returns_file_examples(self):
        """Qdrant 失败后回退到 FileExampleRetriever。"""
        wrapper = _QdrantExampleRetrieverWithFallback()
        with patch("app.vector.retrievers.get_qdrant_manager") as mock_mgr:
            mock_client = MagicMock()
            mock_client.search = AsyncMock(side_effect=Exception("qdrant down"))
            mock_mgr.return_value.client = mock_client

            result = await wrapper.retrieve("查询用户", top_k=3)
            assert isinstance(result, list)
            assert len(result) <= 3


class TestKnowledgeRetrieverFallback:
    def test_returns_qdrant_wrapper(self):
        retriever = get_knowledge_retriever()
        assert retriever is not None
        assert not isinstance(retriever, FileKnowledgeRetriever)

    @pytest.mark.anyio
    async def test_fallback_returns_file_knowledge(self):
        """Qdrant 失败后回退到 FileKnowledgeRetriever。"""
        wrapper = _QdrantKnowledgeRetrieverWithFallback()
        with patch("app.vector.retrievers.get_qdrant_manager") as mock_mgr:
            mock_client = MagicMock()
            mock_client.search = AsyncMock(side_effect=Exception("qdrant down"))
            mock_mgr.return_value.client = mock_client

            result = await wrapper.retrieve("GBase 8a 支持触发器吗")
            assert isinstance(result, list)


class TestLLMClient:
    def test_returns_lite_llm_impl(self):
        client = get_llm_client()
        assert isinstance(client, LiteLLMClientImpl)

    def test_model_override(self):
        client = get_llm_client(model="openai/gpt-4o")
        assert isinstance(client, LiteLLMClientImpl)
