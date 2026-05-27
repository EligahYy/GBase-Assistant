"""对话摘要生成器：长期记忆实现。"""

from __future__ import annotations

import json
import logging
import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.conversation_summary import ConversationSummary
from app.models.message import Message
from app.protocols import LLMClient

logger = logging.getLogger(__name__)

SUMMARY_PROMPT = """请对以下数据库对话生成结构化摘要。对话是用户与 AI 助手关于 GBase 8a 数据库的交互。

要求输出严格 JSON 格式：
{
  "summary": "一句话概括对话主题（30字以内）",
  "key_sql": "对话中生成的最关键的一条 SQL（如果有的话，没有则留空）",
  "key_topics": ["涉及的主题1", "涉及的主题2", ...]
}

对话内容：
{dialogue}

只输出 JSON，不要任何其他文字。"""


async def generate_conversation_summary(
    db: AsyncSession,
    conversation_id: str,
    llm_client: LLMClient,
    min_messages: int = 5,
) -> ConversationSummary | None:
    """为指定对话生成摘要。仅在消息数 >= min_messages 时触发。

    Returns:
        新生成的 ConversationSummary，或 None（如果不需要生成）
    """
    # 1. 检查是否已有摘要
    result = await db.execute(select(ConversationSummary).where(ConversationSummary.conversation_id == conversation_id))
    if result.scalar_one_or_none():
        return None

    # 2. 获取对话消息
    result = await db.execute(
        select(Message).where(Message.conversation_id == conversation_id).order_by(Message.created_at.asc())
    )
    messages = list(result.scalars().all())

    if len(messages) < min_messages:
        return None

    # 3. 构建对话文本
    dialogue_lines = []
    for m in messages:
        role = "用户" if m.role == "user" else "AI"
        content = m.content[:500] if len(m.content) > 500 else m.content
        dialogue_lines.append(f"{role}: {content}")
    dialogue = "\n".join(dialogue_lines)

    # 4. 调用 LLM 生成摘要
    try:
        prompt = SUMMARY_PROMPT.format(dialogue=dialogue)
        content, _ = await llm_client.complete([{"role": "user", "content": prompt}])

        # 解析 JSON
        content = content.strip()
        if content.startswith("```json"):
            content = content[7:]
        if content.startswith("```"):
            content = content[3:]
        if content.endswith("```"):
            content = content[:-3]
        content = content.strip()

        parsed = json.loads(content)

        summary = ConversationSummary(
            id=str(uuid.uuid4()),
            conversation_id=conversation_id,
            summary=parsed.get("summary", ""),
            key_sql=parsed.get("key_sql", ""),
            key_topics=json.dumps(parsed.get("key_topics", []), ensure_ascii=False),
        )
        db.add(summary)
        await db.commit()

        logger.info(
            "对话摘要生成完成: conversation_id=%s, messages=%d, summary=%.40s",
            conversation_id,
            len(messages),
            summary.summary,
        )
        return summary

    except json.JSONDecodeError as e:
        logger.warning("摘要 JSON 解析失败: %s | raw=%.100s", e, content)
        return None
    except Exception as e:
        logger.warning("摘要生成失败: %s", e)
        return None
