"""对话上下文、消息持久化与反馈相关服务。"""

from __future__ import annotations

import json
import logging
import re
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation import Conversation
from app.models.conversation_summary import ConversationSummary
from app.models.message import Message
from app.models.sql_feedback import SQLFeedback
from app.protocols import ChatContext
from app.schemas.chat import ConversationResponse, MessageResponse

logger = logging.getLogger(__name__)

HISTORY_TOKEN_BUDGET = 8000


async def get_or_create_conversation(
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


def estimate_tokens(text: str) -> int:
    """粗略估算混合中文、英文和 SQL 内容的 token 数。"""
    cn_chars = len(re.findall(r"[\u4e00-\u9fff]", text))
    en_words = len(re.findall(r"[a-zA-Z]+", text))
    symbols = len(re.findall(r"[0-9\-_=+<>!@#$%^&*(){\[\]}|;:'\",./?`~]", text))
    code_blocks = len(re.findall(r"```[\s\S]*?```", text))
    code_bonus = code_blocks * 30

    base = cn_chars + int(en_words * 1.3) + int(symbols * 0.5) + 5 + code_bonus
    if code_blocks:
        base = int(base * 1.2)
    return base


async def build_context(db: AsyncSession, conv: Conversation) -> ChatContext:
    """构建对话上下文（token 感知截断）。"""
    result = await db.execute(
        select(Message).where(Message.conversation_id == conv.id).order_by(Message.created_at.desc()).limit(100)
    )
    messages = list(reversed(result.scalars().all()))

    history: list[dict] = []
    total_tokens = 0
    skipped = 0
    for m in reversed(messages):
        msg_tokens = estimate_tokens(m.content)
        if total_tokens + msg_tokens > HISTORY_TOKEN_BUDGET and history:
            skipped += 1
            continue
        history.insert(0, {"role": m.role, "content": m.content})
        total_tokens += msg_tokens

    if skipped:
        logger.info(
            "对话上下文截断：总消息 %d 条，保留最近 %d 条（约 %d tokens），跳过最早 %d 条",
            len(messages),
            len(history),
            total_tokens,
            skipped,
        )
    else:
        logger.info("对话上下文完整保留：%d 条消息（约 %d tokens）", len(history), total_tokens)

    return ChatContext(
        db_id=conv.db_connection_id,
        conversation_id=conv.id,
        history=history,
    )


async def save_messages(
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

    if not conv.title:
        conv.title = user_content[:30] + ("..." if len(user_content) > 30 else "")

    await db.commit()
    return user_msg, assistant_msg


def parse_tags(tags_str: str | None) -> list[str]:
    """解析 Conversation.tags 中的 JSON 字符串。"""
    if not tags_str:
        return []
    try:
        parsed = json.loads(tags_str)
        return parsed if isinstance(parsed, list) else []
    except (json.JSONDecodeError, ValueError):
        return []


def serialize_conversation(conv: Conversation, include_messages: bool = True) -> ConversationResponse:
    """手动序列化 Conversation ORM 对象，避免 relationship 与 Pydantic 兼容细节泄漏到 API 层。"""
    return ConversationResponse(
        id=conv.id,
        title=conv.title,
        db_connection_id=conv.db_connection_id,
        model_used=conv.model_used,
        archived=conv.archived,
        tags=parse_tags(conv.tags),
        created_at=conv.created_at,
        messages=[MessageResponse.from_orm_model(m) for m in conv.messages] if include_messages else [],
    )


async def get_conversation_summary_payload(conversation_id: str, db: AsyncSession) -> dict:
    """获取对话摘要响应结构。"""
    result = await db.execute(select(ConversationSummary).where(ConversationSummary.conversation_id == conversation_id))
    summary = result.scalar_one_or_none()
    if not summary:
        return {"has_summary": False}

    key_topics = []
    if summary.key_topics:
        try:
            key_topics = json.loads(summary.key_topics)
        except json.JSONDecodeError:
            pass

    return {
        "has_summary": True,
        "summary": summary.summary,
        "key_sql": summary.key_sql,
        "key_topics": key_topics,
        "created_at": summary.created_at.isoformat() if summary.created_at else None,
    }


async def create_sql_feedback(db: AsyncSession, payload: dict) -> dict[str, str | bool]:
    """提交 SQL 反馈。"""
    message_id = payload.get("message_id")
    action = payload.get("action")
    original_sql = payload.get("original_sql")

    if action not in ("accepted", "rejected", "modified"):
        raise ValueError("action must be accepted/rejected/modified")

    result = await db.execute(select(Message).where(Message.id == message_id))
    msg = result.scalar_one_or_none()
    if not msg and not original_sql:
        raise LookupError("消息不存在且未提供 original_sql")

    feedback = SQLFeedback(
        id=str(uuid.uuid4()),
        message_id=msg.id if msg else None,
        action=action,
        original_sql=original_sql or (msg.sql_generated if msg else None),
        modified_sql=payload.get("modified_sql"),
        feedback_note=payload.get("feedback_note"),
    )
    db.add(feedback)
    await db.commit()
    return {"ok": True, "id": feedback.id}
