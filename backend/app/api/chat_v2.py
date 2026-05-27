"""v2 Chat API — LangGraph 多 Agent + AG-UI 事件流。

与 v1 /api/chat/stream 并存，不破坏现有功能。
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Body
from fastapi.responses import StreamingResponse

from app.agents.graph import run_agent_with_ag_ui
from app.schemas.chat import ChatRequest

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/v2/chat", tags=["chat-v2"])


@router.post("/stream")
async def chat_stream_v2(request: ChatRequest = Body(...)):
    """v2 流式聊天接口 — AG-UI 标准 SSE 事件流。

    复用 v1 的 ChatRequest schema，输出升级为 AG-UI 事件类型。
    """
    conversation_id = request.conversation_id or ""

    event_stream = run_agent_with_ag_ui(
        user_message=request.message,
        conversation_id=conversation_id,
        model=request.model or "deepseek/deepseek-chat",
        db_connection_id=request.db_connection_id,
    )

    return StreamingResponse(
        event_stream,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Conversation-Id": conversation_id,
        },
    )
