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

    # Wrap stream to persist conversation after completion
    async def persistent_stream():
        async for event in event_stream:
            yield event
        # Persist after stream completes
        if conversation_id:
            try:
                from app.database import async_session_factory
                from app.models.conversation import Conversation
                from app.models.message import Message
                from sqlalchemy import select
                import uuid
                from datetime import UTC, datetime

                async with async_session_factory() as db:
                    # Get or create conversation
                    result = await db.execute(
                        select(Conversation).where(Conversation.id == conversation_id)
                    )
                    conv = result.scalar_one_or_none()
                    if not conv:
                        conv = Conversation(
                            id=conversation_id,
                            title=request.message[:50],
                            db_connection_id=request.db_connection_id,
                            model_used=request.model,
                            created_at=datetime.now(UTC),
                        )
                        db.add(conv)

                    # Save user message
                    user_msg = Message(
                        id=str(uuid.uuid4()),
                        conversation_id=conversation_id,
                        role="user",
                        content=request.message,
                        created_at=datetime.now(UTC),
                    )
                    db.add(user_msg)

                    await db.commit()
            except Exception as e:
                logger.warning("Failed to persist v2 conversation: %s", e)

    return StreamingResponse(
        persistent_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
            "X-Conversation-Id": conversation_id,
        },
    )
