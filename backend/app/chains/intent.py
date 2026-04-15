"""意图分类：通过 LLM + few-shot prompt 判断用户意图。"""
from __future__ import annotations

import json
import logging

from app.llm.prompts import INTENT_SYSTEM
from app.protocols import LLMClient

logger = logging.getLogger(__name__)

VALID_INTENTS = frozenset(["sql", "qa", "general"])


async def classify_intent(message: str, llm_client: LLMClient) -> str:
    """
    判断用户意图，返回 "sql" | "qa" | "general"。
    失败时默认返回 "general"（安全降级）。
    """
    messages = [
        {"role": "system", "content": INTENT_SYSTEM},
        {"role": "user", "content": message},
    ]
    try:
        content, _ = await llm_client.complete(messages, temperature=0.0, max_tokens=50)
        # 解析 JSON
        content = content.strip()
        # LLM 有时会输出 ```json ... ``` 或多余文字，提取 JSON 部分
        if "{" in content:
            start = content.index("{")
            end = content.rindex("}") + 1
            content = content[start:end]
        data = json.loads(content)
        intent = data.get("intent", "general")
        if intent not in VALID_INTENTS:
            logger.warning("未知意图值: %s，降级为 general", intent)
            return "general"
        return intent
    except Exception as e:
        logger.warning("意图分类失败: %s，降级为 general", e)
        return "general"
