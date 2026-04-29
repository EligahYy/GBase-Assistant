"""通过 LiteLLM 调用远程 Embedding API（OpenAI / 兼容 API）。"""

from __future__ import annotations

import logging

import litellm

from app.config import get_settings

logger = logging.getLogger(__name__)


class LiteLLMEmbedder:
    """基于 LiteLLM 的远程 embedding 封装。

    支持：openai/text-embedding-3-small、openai/text-embedding-3-large、
          voyage/voyage-3、等所有 LiteLLM 支持的 embedding 模型。
    """

    def __init__(self, model: str = "openai/text-embedding-3-small") -> None:
        self._model = model
        self._dimension = 1536  # text-embedding-3-small 默认维度
        if "large" in model:
            self._dimension = 3072

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        settings = get_settings()
        # 注入 API keys（LiteLLM 从环境变量读取）
        if settings.deepseek_api_key:
            import os

            os.environ.setdefault("DEEPSEEK_API_KEY", settings.deepseek_api_key)
        if settings.openai_api_key:
            import os

            os.environ.setdefault("OPENAI_API_KEY", settings.openai_api_key)

        response = await litellm.aembedding(model=self._model, input=texts)
        return [item["embedding"] for item in response.data]

    @property
    def dimension(self) -> int:
        return self._dimension
