"""v2 Chat API 集成测试。"""

import os

os.environ["TESTING"] = "1"

import pytest
from httpx import ASGITransport, AsyncClient

from app.main import create_app

app = create_app()


@pytest.mark.asyncio
async def test_v2_chat_stream_responds_ag_ui_events():
    """v2 端点应返回 AG-UI 标准事件。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/chat/stream",
            json={"message": "你好", "model": "deepseek/deepseek-chat"},
            headers={"Accept": "text/event-stream"},
            timeout=10,
        )
        assert response.status_code == 200
        assert "text/event-stream" in response.headers.get("content-type", "")

        body = response.text
        assert "RUN_STARTED" in body, f"Missing RUN_STARTED in: {body[:200]}"
        assert "RUN_FINISHED" in body, f"Missing RUN_FINISHED in: {body[:200]}"


@pytest.mark.asyncio
async def test_v2_chat_sql_intent():
    """SQL 意图应产生流式 TEXT_MESSAGE_CONTENT 和 RUN_FINISHED。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/chat/stream",
            json={"message": "查询所有订单", "model": "deepseek/deepseek-chat"},
            headers={"Accept": "text/event-stream"},
            timeout=10,
        )
        body = response.text
        assert "TEXT_MESSAGE_CONTENT" in body, f"Missing TEXT_MESSAGE_CONTENT: {body[:300]}"
        assert "RUN_FINISHED" in body, f"Missing RUN_FINISHED: {body[:300]}"


@pytest.mark.asyncio
async def test_v2_chat_general_intent():
    """通用意图应产生流式 TEXT_MESSAGE_CONTENT 回复。"""
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.post(
            "/api/chat/stream",
            json={"message": "你好", "model": "deepseek/deepseek-chat"},
            headers={"Accept": "text/event-stream"},
            timeout=10,
        )
        body = response.text
        assert "TEXT_MESSAGE_CONTENT" in body, f"Missing TEXT_MESSAGE_CONTENT: {body[:300]}"
