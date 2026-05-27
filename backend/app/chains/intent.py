"""意图分类：通过 LLM + few-shot prompt 判断用户意图。"""

from __future__ import annotations

import json
import logging

from app.llm.prompts import INTENT_SYSTEM
from app.protocols import LLMClient

logger = logging.getLogger(__name__)

VALID_INTENTS = frozenset(["sql", "qa", "general"])

SQL_KEYWORDS = (
    "查询",
    "统计",
    "列出",
    "筛选",
    "分析",
    "计算",
    "订单",
    "用户",
    "表",
    "字段",
    "sql",
)
QA_KEYWORDS = (
    "介绍",
    "解释",
    "说明",
    "支持",
    "怎么",
    "如何",
    "什么",
    "区别",
    "错误",
    "函数",
    "语法",
    "gbase",
    "row number",
    "row_number",
)


async def classify_intent(message: str, llm_client: LLMClient) -> str:
    """
    判断用户意图，返回 "sql" | "qa" | "general"。
    失败时使用本地关键词兜底，避免 LLM 认证问题导致数据库问题被误路由到 general。
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
        fallback = classify_intent_by_rule(message)
        logger.warning("意图分类失败: %s，使用本地规则降级为 %s", e, fallback)
        return fallback


def classify_intent_by_rule(message: str) -> str:
    """轻量本地兜底分类，避免模型不可用时聊天链路完全中断。"""
    normalized = message.lower()
    if any(keyword in normalized for keyword in QA_KEYWORDS):
        return "qa"
    if any(keyword in normalized for keyword in SQL_KEYWORDS):
        return "sql"
    return "general"
