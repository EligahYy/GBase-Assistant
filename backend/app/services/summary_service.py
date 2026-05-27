"""对话摘要后台任务服务。"""

from __future__ import annotations

import logging
import os

from app.database import async_session_factory
from app.dependencies import get_llm_client
from app.jobs.summary_generator import generate_conversation_summary

logger = logging.getLogger(__name__)


async def trigger_summary_generation(
    conversation_id: str,
    model: str | None,
) -> None:
    """后台生成对话摘要；失败只记录日志，不影响主请求。"""
    if os.getenv("TESTING"):
        return
    try:
        async with async_session_factory() as db:
            llm_client = get_llm_client(model, task_type="knowledge_qa")
            await generate_conversation_summary(db, conversation_id, llm_client, min_messages=5)
    except Exception as e:
        logger.warning("摘要生成后台任务失败: %s", e)
