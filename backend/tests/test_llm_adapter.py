"""Contracts for preserving function-calling messages through LiteLLM."""

from unittest.mock import AsyncMock

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolCall, ToolMessage

from app.llm.adapter import LiteLLMChatAdapter


@pytest.mark.asyncio
async def test_adapter_preserves_assistant_tool_calls_and_tool_role():
    client = AsyncMock()
    client.complete.return_value = ("done", {}, None)
    adapter = LiteLLMChatAdapter(client)
    messages = [
        HumanMessage(content="查询订单"),
        AIMessage(
            content="",
            tool_calls=[ToolCall(name="search_schemas", args={"query": "订单"}, id="call-1")],
        ),
        ToolMessage(content="orders", tool_call_id="call-1"),
    ]

    await adapter._agenerate(messages)

    sent = client.complete.await_args.args[0]
    assert sent[1]["role"] == "assistant"
    assert sent[1]["tool_calls"][0]["function"]["name"] == "search_schemas"
    assert sent[2] == {"role": "tool", "content": "orders", "tool_call_id": "call-1"}
