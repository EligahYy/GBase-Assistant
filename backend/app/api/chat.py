"""聊天 API — v2 多智能体 AG-UI 流式聊天 + 对话管理。"""

from __future__ import annotations

import json
import logging
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.agents.graph import run_agent_with_ag_ui
from app.database import get_db
from app.models.conversation import Conversation
from app.schemas.chat import ChatRequest, ConversationResponse
from app.services.conversation_service import (
    create_sql_feedback,
    get_conversation_summary_payload,
    serialize_conversation,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


@router.post("/stream")
async def chat_stream(
    request: ChatRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """流式聊天接口 — AG-UI 标准 SSE 事件流（多智能体协作）。"""
    conversation_id = request.conversation_id or str(uuid.uuid4())

    event_stream = run_agent_with_ag_ui(
        user_message=request.message,
        conversation_id=conversation_id,
        model=request.model or "deepseek/deepseek-chat",
        db_connection_id=request.db_connection_id,
    )

    async def persistent_stream():
        async for event in event_stream:
            yield event
        if conversation_id:
            try:
                from app.models.conversation import Conversation
                from app.models.message import Message
                from sqlalchemy import select
                from datetime import UTC, datetime

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
                logger.warning("Failed to persist conversation: %s", e)

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


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.archived.is_(False))
        .order_by(Conversation.updated_at.desc())
        .limit(50)
    )
    convs = result.scalars().all()
    return [serialize_conversation(c) for c in convs]


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Conversation).options(selectinload(Conversation.messages)).where(Conversation.id == conversation_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    return serialize_conversation(conv)


@router.get("/conversations/{conversation_id}/summary")
async def get_conversation_summary(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """获取对话摘要（长期记忆）。"""
    return await get_conversation_summary_payload(conversation_id, db)


@router.patch("/conversations/{conversation_id}")
async def update_conversation(
    conversation_id: str,
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """更新对话信息。payload: {"title": "新标题", "archived": true, "tags": ["a", "b"]}"""
    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    if "title" in payload:
        conv.title = payload["title"][:200] if payload["title"] else None
    if "archived" in payload:
        conv.archived = bool(payload["archived"])
    if "tags" in payload:
        tags = payload["tags"]
        conv.tags = json.dumps(tags, ensure_ascii=False) if isinstance(tags, list) else str(tags)
    await db.commit()
    return {"ok": True}


@router.delete("/conversations/{conversation_id}")
async def delete_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    """删除对话及其所有消息。"""
    result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    await db.delete(conv)
    await db.commit()
    return {"ok": True}


@router.post("/feedback")
async def create_feedback(
    payload: dict = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """Submit SQL feedback: { message_id, action, original_sql?, modified_sql?, feedback_note? }"""
    try:
        return await create_sql_feedback(db, payload)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e)) from e
    except LookupError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
