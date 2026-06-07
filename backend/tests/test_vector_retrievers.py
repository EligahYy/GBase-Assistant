from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.vector.retrievers import QdrantKnowledgeRetriever


@pytest.mark.anyio
async def test_knowledge_retriever_uses_query_points_and_returns_chapter_title():
    embedder = MagicMock()
    embedder.embed = AsyncMock(return_value=[[0.1, 0.2]])
    point = SimpleNamespace(
        payload={
            "title": "5.1.8.2.1 CREATE TABLE",
            "source": "GBase 8a MPP Cluster产品手册",
            "content": "不指定 DISTRIBUTED BY 时创建随机分布表。",
        }
    )
    client = MagicMock()
    client.query_points = AsyncMock(return_value=SimpleNamespace(points=[point]))

    with (
        patch("app.vector.retrievers.get_embedder", return_value=embedder),
        patch("app.vector.retrievers.get_qdrant_manager", return_value=SimpleNamespace(client=client)),
    ):
        results = await QdrantKnowledgeRetriever().retrieve("如何创建随机分布表？")

    client.query_points.assert_awaited_once()
    assert results[0].source == "5.1.8.2.1 CREATE TABLE"
    assert "随机分布表" in results[0].content
