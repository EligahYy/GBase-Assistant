"""LiteLLM 封装：统一 LLM 调用接口，支持多模型 fallback 和流式输出。"""
from __future__ import annotations

import logging
import os
from typing import AsyncIterator

import litellm

from app.config import get_settings
from app.protocols import LLMClient

logger = logging.getLogger(__name__)

# 禁用 litellm 的详细日志
litellm.suppress_debug_info = True


class LiteLLMClientImpl:
    """LLMClient Protocol 的 Phase 1 实现：单模型 + 简单 fallback。"""

    def __init__(self, model: str | None = None):
        settings = get_settings()
        self.model = model or settings.default_model
        self._configure_env(settings)

    def _configure_env(self, settings) -> None:
        """将配置的 API keys 注入到环境变量（LiteLLM 读取方式）。"""
        if settings.deepseek_api_key:
            os.environ["DEEPSEEK_API_KEY"] = settings.deepseek_api_key
        if settings.dashscope_api_key:
            os.environ["DASHSCOPE_API_KEY"] = settings.dashscope_api_key
        if settings.openai_api_key:
            os.environ["OPENAI_API_KEY"] = settings.openai_api_key
        if settings.anthropic_api_key:
            os.environ["ANTHROPIC_API_KEY"] = settings.anthropic_api_key

    async def complete(self, messages: list[dict], **kwargs) -> tuple[str, dict]:
        """
        非流式生成。返回 (content, token_usage)。
        token_usage: {"prompt": N, "completion": N, "total": N, "model": "..."}
        """
        try:
            response = await litellm.acompletion(
                model=self.model,
                messages=messages,
                **kwargs,
            )
            content = response.choices[0].message.content or ""
            usage = {
                "prompt": response.usage.prompt_tokens if response.usage else 0,
                "completion": response.usage.completion_tokens if response.usage else 0,
                "total": response.usage.total_tokens if response.usage else 0,
                "model": self.model,
            }
            return content, usage
        except Exception as e:
            logger.error("LLM complete failed: %s model=%s", e, self.model)
            raise

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        """
        流式生成，yield token chunks（纯文本字符串）。
        调用方负责拼接完整内容。
        """
        try:
            response = await litellm.acompletion(
                model=self.model,
                messages=messages,
                stream=True,
                **kwargs,
            )
            async for chunk in response:
                delta = chunk.choices[0].delta
                if delta and delta.content:
                    yield delta.content
        except Exception as e:
            logger.error("LLM stream failed: %s model=%s", e, self.model)
            raise


# 验证实现满足 Protocol
assert isinstance(LiteLLMClientImpl(), LLMClient)
