"""聊天 API：HTTP 入参/出参与服务层绑定。"""

from __future__ import annotations

import json

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.database import get_db
from app.dependencies import get_example_retriever, get_knowledge_retriever, get_schema_retriever
from app.models.conversation import Conversation
from app.protocols import ExampleRetriever, KnowledgeRetriever
from app.schemas.chat import ChatRequest, ChatResponse, ConversationResponse
from app.services.chat_service import ChatService
from app.services.conversation_service import (
    create_sql_feedback,
    get_conversation_summary_payload,
    serialize_conversation,
)

router = APIRouter(prefix="/chat", tags=["chat"])


def _build_chat_service(
    db: AsyncSession,
    example_retriever: ExampleRetriever,
    knowledge_retriever: KnowledgeRetriever,
) -> ChatService:
    """构建聊天服务，API 层只负责依赖装配。"""
    return ChatService(
        db=db,
        schema_retriever=get_schema_retriever(db),
        example_retriever=example_retriever,
        knowledge_retriever=knowledge_retriever,
    )


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    example_retriever: ExampleRetriever = Depends(get_example_retriever),
    knowledge_retriever: KnowledgeRetriever = Depends(get_knowledge_retriever),
):
    """非流式聊天接口。"""
    service = _build_chat_service(db, example_retriever, knowledge_retriever)
    return await service.run(request)


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    example_retriever: ExampleRetriever = Depends(get_example_retriever),
    knowledge_retriever: KnowledgeRetriever = Depends(get_knowledge_retriever),
):
    """流式聊天接口，返回 SSE。"""
    service = _build_chat_service(db, example_retriever, knowledge_retriever)
    conversation_id, events = await service.stream(request)
    return StreamingResponse(
        events,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
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
