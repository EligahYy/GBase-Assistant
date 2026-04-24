"""聊天 API：非流式 POST /api/chat 和流式 POST /api/chat/stream。"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.chains.intent import classify_intent
from app.chains.qa_chain import run_qa_chain, stream_qa_chain
from app.chains.sql_chain import run_sql_chain, stream_sql_chain
from app.database import get_db
from app.dependencies import get_example_retriever, get_knowledge_retriever, get_llm_client
from app.knowledge.loader import DbSchemaRetriever
from app.models.conversation import Conversation
from app.models.message import Message
from app.models.sql_feedback import SQLFeedback
from app.protocols import ChatContext, ExampleRetriever, KnowledgeRetriever, LLMClient
from app.schemas.chat import ChatRequest, ChatResponse, ConversationResponse, MessageResponse

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/chat", tags=["chat"])


async def _get_or_create_conversation(
    db: AsyncSession,
    conversation_id: str | None,
    db_connection_id: str | None,
    model: str | None,
) -> Conversation:
    """获取已有对话或创建新对话。"""
    if conversation_id:
        result = await db.execute(select(Conversation).where(Conversation.id == conversation_id))
        conv = result.scalar_one_or_none()
        if conv:
            return conv

    conv = Conversation(
        id=str(uuid.uuid4()),
        title=None,
        db_connection_id=db_connection_id,
        model_used=model,
    )
    db.add(conv)
    await db.flush()
    return conv


def _estimate_tokens(text: str) -> int:
    """简易 token 估算：中文按字符，英文按单词数 * 1.3。"""
    import re
    # 中文字符
    cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    # 英文单词
    en_words = len(re.findall(r"[a-zA-Z]+", text))
    return cn_chars + int(en_words * 1.3) + 5  # +5 作为格式开销


HISTORY_TOKEN_BUDGET = 4000


async def _build_context(db: AsyncSession, conv: Conversation) -> ChatContext:
    """构建对话上下文（token 感知截断）。"""
    result = await db.execute(
        select(Message)
        .where(Message.conversation_id == conv.id)
        .order_by(Message.created_at.desc())
        .limit(50)
    )
    messages = list(reversed(result.scalars().all()))

    # Token 感知截断：从最近的消息开始保留，直到预算用完
    history: list[dict] = []
    total_tokens = 0
    for m in reversed(messages):
        msg_tokens = _estimate_tokens(m.content)
        if total_tokens + msg_tokens > HISTORY_TOKEN_BUDGET and history:
            logger.info("对话上下文截断：保留最近 %d 条消息，跳过 %d 条", len(history), len(messages) - len(history))
            break
        history.insert(0, {"role": m.role, "content": m.content})
        total_tokens += msg_tokens

    return ChatContext(
        db_id=conv.db_connection_id,
        conversation_id=conv.id,
        history=history,
    )


async def _save_messages(
    db: AsyncSession,
    conv: Conversation,
    user_content: str,
    result_content: str,
    message_type: str,
    sql_generated: str | None,
    sql_validated: bool | None,
    token_usage: dict | None,
) -> tuple[Message, Message]:
    """保存用户消息和助手消息。"""
    user_msg = Message(
        id=str(uuid.uuid4()),
        conversation_id=conv.id,
        role="user",
        content=user_content,
    )
    db.add(user_msg)

    assistant_msg = Message(
        id=str(uuid.uuid4()),
        conversation_id=conv.id,
        role="assistant",
        content=result_content,
        message_type=message_type,
        sql_generated=sql_generated,
        sql_validated=sql_validated,
    )
    assistant_msg.set_token_usage(token_usage)
    db.add(assistant_msg)

    # 如果是对话的第一条消息，用用户消息前 30 字作为标题
    if not conv.title:
        conv.title = user_content[:30] + ("..." if len(user_content) > 30 else "")

    await db.commit()
    return user_msg, assistant_msg


@router.post("", response_model=ChatResponse)
async def chat(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    example_retriever: ExampleRetriever = Depends(get_example_retriever),
    knowledge_retriever: KnowledgeRetriever = Depends(get_knowledge_retriever),
):
    """非流式聊天接口。"""
    llm_client: LLMClient = get_llm_client(request.model, task_type="intent_classification")
    schema_retriever = DbSchemaRetriever(db)

    conv = await _get_or_create_conversation(db, request.conversation_id, request.db_connection_id, request.model)
    context = await _build_context(db, conv)

    # 意图分类
    intent = await classify_intent(request.message, llm_client)
    logger.info("意图分类: %s | 消息: %.50s", intent, request.message)

    # 按意图创建 task-specific LLM client
    task_type = "sql_generation" if intent == "sql" else ("knowledge_qa" if intent == "qa" else "general")
    llm_client = get_llm_client(request.model, task_type=task_type)

    # 执行对应 chain
    if intent == "sql":
        chat_result = await run_sql_chain(request.message, context, schema_retriever, example_retriever, llm_client)
    elif intent == "qa":
        chat_result = await run_qa_chain(request.message, context, knowledge_retriever, llm_client)
    else:
        from app.llm.prompts import build_general_prompt
        content, token_usage = await llm_client.complete(build_general_prompt(request.message, context.history))
        from app.protocols import ChatResult
        chat_result = ChatResult(content=content, message_type="general", token_usage=token_usage)

    _, assistant_msg = await _save_messages(
        db, conv,
        user_content=request.message,
        result_content=chat_result.content,
        message_type=chat_result.message_type,
        sql_generated=chat_result.sql,
        sql_validated=chat_result.validation.is_valid if chat_result.validation else None,
        token_usage=chat_result.token_usage,
    )

    return ChatResponse(
        conversation_id=conv.id,
        message=MessageResponse.from_orm_model(assistant_msg),
    )


@router.post("/stream")
async def chat_stream(
    request: ChatRequest,
    db: AsyncSession = Depends(get_db),
    example_retriever: ExampleRetriever = Depends(get_example_retriever),
    knowledge_retriever: KnowledgeRetriever = Depends(get_knowledge_retriever),
):
    """流式聊天接口，返回 SSE。"""
    llm_client: LLMClient = get_llm_client(request.model, task_type="intent_classification")
    schema_retriever = DbSchemaRetriever(db)

    conv = await _get_or_create_conversation(db, request.conversation_id, request.db_connection_id, request.model)
    context = await _build_context(db, conv)

    intent = await classify_intent(request.message, llm_client)
    logger.info("流式意图分类: %s | 消息: %.50s", intent, request.message)

    # 按意图创建 task-specific LLM client
    task_type = "sql_generation" if intent == "sql" else ("knowledge_qa" if intent == "qa" else "general")
    llm_client = get_llm_client(request.model, task_type=task_type)

    async def event_generator():
        full_content = ""
        sql_content = None
        sql_validated = None
        token_usage = None

        try:
            if intent == "sql":
                stream = stream_sql_chain(request.message, context, schema_retriever, example_retriever, llm_client)
            elif intent == "qa":
                stream = stream_qa_chain(request.message, context, knowledge_retriever, llm_client)
            else:
                from app.llm.prompts import build_general_prompt
                from app.protocols import StreamChunk

                async def general_stream():
                    async for token in llm_client.stream(build_general_prompt(request.message, context.history)):
                        yield StreamChunk(type="text", content=token)
                    yield StreamChunk(type="done", content="", token_usage={})

                stream = general_stream()

            async for chunk in stream:
                if chunk.type == "text":
                    full_content += chunk.content
                elif chunk.type == "sql":
                    sql_content = chunk.content
                elif chunk.type == "warning":
                    full_content += f"\n\n{chunk.content}"
                    # If warning from SQL validation, mark as invalid
                    if sql_content and "⚠️" in chunk.content:
                        sql_validated = False
                elif chunk.type == "done":
                    token_usage = chunk.token_usage
                yield chunk.to_sse()

            # If sql was generated but no validation warning was issued, mark as valid
            if sql_content is not None and sql_validated is None:
                sql_validated = True

        except Exception as e:
            logger.error("流式生成错误: %s", e)
            from app.protocols import StreamChunk
            yield StreamChunk(type="error", content=f"生成失败：{e!s}").to_sse()
            return

        # 保存消息（流结束后）
        try:
            await _save_messages(
                db, conv,
                user_content=request.message,
                result_content=full_content,
                message_type=intent,
                sql_generated=sql_content,
                sql_validated=sql_validated,
                token_usage=token_usage,
            )
        except Exception as e:
            logger.error("保存消息失败: %s", e)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "X-Conversation-Id": conv.id,
        },
    )


import json


def _parse_tags(tags_str: str | None) -> list[str]:
    if not tags_str:
        return []
    try:
        return json.loads(tags_str)
    except (json.JSONDecodeError, ValueError):
        return []


def _serialize_conversation(conv: Conversation, include_messages: bool = True) -> ConversationResponse:
    """手动序列化 Conversation ORM 对象，绕过 Pydantic from_attributes 对 InstrumentedList 的兼容问题。"""
    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        db_connection_id=conv.db_connection_id,
        model_used=conv.model_used,
        archived=conv.archived,
        tags=_parse_tags(conv.tags),
        created_at=conv.created_at,
        messages=[MessageResponse.from_orm_model(m) for m in conv.messages] if include_messages else [],
    )


@router.get("/conversations", response_model=list[ConversationResponse])
async def list_conversations(db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.archived == False)
        .order_by(Conversation.updated_at.desc())
        .limit(50)
    )
    convs = result.scalars().all()
    return [_serialize_conversation(c) for c in convs]


@router.get("/conversations/{conversation_id}", response_model=ConversationResponse)
async def get_conversation(conversation_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(Conversation)
        .options(selectinload(Conversation.messages))
        .where(Conversation.id == conversation_id)
    )
    conv = result.scalar_one_or_none()
    if not conv:
        raise HTTPException(status_code=404, detail="对话不存在")
    return _serialize_conversation(conv)


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
    """Submit SQL feedback: { message_id, action, modified_sql?, feedback_note? }"""
    message_id = payload.get("message_id")
    action = payload.get("action")

    if action not in ("accepted", "rejected", "modified"):
        raise HTTPException(status_code=422, detail="action must be accepted/rejected/modified")

    result = await db.execute(select(Message).where(Message.id == message_id))
    msg = result.scalar_one_or_none()
    if not msg:
        raise HTTPException(status_code=404, detail="消息不存在")

    feedback = SQLFeedback(
        id=str(uuid.uuid4()),
        message_id=message_id,
        action=action,
        original_sql=msg.sql_generated,
        modified_sql=payload.get("modified_sql"),
        feedback_note=payload.get("feedback_note"),
    )
    db.add(feedback)
    await db.commit()
    return {"ok": True, "id": feedback.id}
