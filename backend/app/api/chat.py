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
from app.schemas.chat import BatchRequest, ChatRequest, ConversationResponse, FolderResponse
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

    # 在流开始之前先保存用户消息，确保对话在侧边栏中立即可见
    # 即使流被中断（如用户切换对话），对话记录也不会丢失
    user_message_id = str(uuid.uuid4())
    try:
        from datetime import UTC, datetime
        from app.models.message import Message

        if not request.conversation_id:
            conv = Conversation(
                id=conversation_id,
                title=request.message[:50],
                db_connection_id=request.db_connection_id,
                model_used=request.model,
                folder_id=request.folder_id,
                created_at=datetime.now(UTC),
            )
            db.add(conv)

        user_msg = Message(
            id=user_message_id,
            conversation_id=conversation_id,
            role="user",
            content=request.message,
            created_at=datetime.now(UTC),
        )
        db.add(user_msg)
        await db.commit()
    except Exception as e:
        logger.warning("Failed to persist user message before stream: %s", e)

    event_stream = run_agent_with_ag_ui(
        user_message=request.message,
        conversation_id=conversation_id,
        model=request.model or "deepseek/deepseek-chat",
        db_connection_id=request.db_connection_id,
    )

    async def persistent_stream():
        full_text = ""
        sql_generated = None
        query_result = None
        chart_config = None
        async for event in event_stream:
            # Collect response content from SSE events for persistence
            if event.startswith("data: "):
                data_str = event[6:].strip()
                if data_str and data_str != "[DONE]":
                    try:
                        data = json.loads(data_str)
                        event_type = data.get("type", "")
                        if event_type == "TEXT_MESSAGE_CONTENT":
                            full_text += data.get("delta", "")
                        elif event_type == "STATE_DELTA":
                            path = data.get("path", "")
                            value = data.get("value", {})
                            if path == "sql":
                                sql_generated = value.get("sql", "") if isinstance(value, dict) else str(value)
                            elif path == "result" and isinstance(value, dict):
                                query_result = value
                            elif path == "chart_config" and isinstance(value, dict):
                                chart_config = value
                    except (json.JSONDecodeError, TypeError, AttributeError):
                        pass
            yield event

        # 流结束后只保存助手消息（用户消息已在流开始前保存）
        if conversation_id:
            try:
                if full_text.strip():
                    assistant_msg = Message(
                        id=str(uuid.uuid4()),
                        conversation_id=conversation_id,
                        role="assistant",
                        content=full_text.strip(),
                        message_type="sql" if sql_generated else "general",
                        sql_generated=sql_generated,
                        query_result=json.dumps(query_result) if query_result else None,
                        chart_config=json.dumps(chart_config) if chart_config else None,
                        created_at=datetime.now(UTC),
                    )
                    db.add(assistant_msg)
                    await db.commit()
            except Exception as e:
                logger.warning("Failed to persist assistant message: %s", e)

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
async def list_conversations(
    folder_id: str | None = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.archived.is_(False))
    )
    if folder_id is not None:
        if folder_id == "":
            stmt = stmt.where(Conversation.folder_id.is_(None))
        else:
            stmt = stmt.where(Conversation.folder_id == folder_id)
    stmt = stmt.order_by(Conversation.updated_at.desc()).limit(50)
    result = await db.execute(stmt)
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
    if "folder_id" in payload:
        fid = payload["folder_id"]
        if fid is not None and fid != "":
            from app.models.folder import Folder
            f_result = await db.execute(select(Folder).where(Folder.id == fid))
            if not f_result.scalar_one_or_none():
                raise HTTPException(status_code=404, detail="文件夹不存在")
            conv.folder_id = fid
        else:
            conv.folder_id = None
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


# ── Folder CRUD ──


@router.get("/folders", response_model=list[FolderResponse])
async def list_folders(db: AsyncSession = Depends(get_db)):
    """获取文件夹列表，含对话计数。"""
    from app.models.folder import Folder
    from sqlalchemy import func

    result = await db.execute(
        select(
            Folder,
            func.count(Conversation.id).label("conversation_count"),
        )
        .outerjoin(Conversation, Conversation.folder_id == Folder.id)
        .group_by(Folder.id)
        .order_by(Folder.updated_at.desc())
    )
    rows = result.all()
    return [
        FolderResponse(
            id=folder.id,
            name=folder.name,
            conversation_count=count,
            created_at=folder.created_at,
            updated_at=folder.updated_at,
        )
        for folder, count in rows
    ]


@router.post("/folders", response_model=FolderResponse)
async def create_folder(payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """创建文件夹。"""
    from app.models.folder import Folder

    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="文件夹名称不能为空")
    if len(name) > 100:
        raise HTTPException(status_code=422, detail="文件夹名称不能超过100个字符")

    folder = Folder(name=name)
    db.add(folder)
    await db.commit()
    await db.refresh(folder)
    return FolderResponse(
        id=folder.id,
        name=folder.name,
        conversation_count=0,
        created_at=folder.created_at,
        updated_at=folder.updated_at,
    )


@router.patch("/folders/{folder_id}")
async def update_folder(folder_id: str, payload: dict = Body(...), db: AsyncSession = Depends(get_db)):
    """重命名文件夹。"""
    from app.models.folder import Folder

    result = await db.execute(select(Folder).where(Folder.id == folder_id))
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="文件夹不存在")
    name = payload.get("name", "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="文件夹名称不能为空")
    folder.name = name[:100]
    await db.commit()
    return {"ok": True}


@router.delete("/folders/{folder_id}")
async def delete_folder(folder_id: str, db: AsyncSession = Depends(get_db)):
    """删除文件夹及其中所有对话。"""
    from app.models.folder import Folder

    result = await db.execute(select(Folder).where(Folder.id == folder_id))
    folder = result.scalar_one_or_none()
    if not folder:
        raise HTTPException(status_code=404, detail="文件夹不存在")

    # 级联删除关联对话
    convs_result = await db.execute(
        select(Conversation).where(Conversation.folder_id == folder_id)
    )
    for conv in convs_result.scalars().all():
        await db.delete(conv)
    await db.delete(folder)
    await db.commit()
    return {"ok": True}


# ── Batch Operations ──


@router.post("/conversations/batch")
async def batch_operate_conversations(
    payload: BatchRequest = Body(...),
    db: AsyncSession = Depends(get_db),
):
    """批量操作对话。action: archive | delete | move"""
    from app.models.folder import Folder

    if not payload.ids:
        raise HTTPException(status_code=422, detail="ids 不能为空")

    if payload.action == "move":
        if not payload.folder_id:
            raise HTTPException(status_code=422, detail="move 操作需要 folder_id")
        f_result = await db.execute(select(Folder).where(Folder.id == payload.folder_id))
        if not f_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="目标文件夹不存在")

    result = await db.execute(
        select(Conversation).where(Conversation.id.in_(payload.ids))
    )
    convs = result.scalars().all()

    if payload.action == "archive":
        for c in convs:
            c.archived = True
    elif payload.action == "delete":
        for c in convs:
            await db.delete(c)
    elif payload.action == "move":
        for c in convs:
            c.folder_id = payload.folder_id
    else:
        raise HTTPException(status_code=422, detail="不支持的操作")

    await db.commit()
    return {"ok": True, "affected": len(convs)}
