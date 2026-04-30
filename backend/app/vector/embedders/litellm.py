"""通过 LiteLLM 调用远程 Embedding API（OpenAI / 阿里云 / 等兼容 API）。"""

from __future__ import annotations

import logging

import litellm

from app.config import get_settings

logger = logging.getLogger(__name__)

# 阿里云 text-embedding-v4 维度
DASHSCOPE_DIM = 1024


class LiteLLMEmbedder:
    """基于 LiteLLM 的远程 embedding 封装。

    支持：openai/text-embedding-3-small、阿里云 text-embedding-v4、
          voyage/voyage-3、等所有 LiteLLM 支持的 embedding 模型。
    """

    def __init__(
        self,
        model: str = "openai/text-embedding-3-small",
        api_base: str | None = None,
    ) -> None:
        self._model = model
        self._api_base = api_base
        # 维度映射
        if "text-embedding-v4" in model:
            self._dimension = DASHSCOPE_DIM
        elif "large" in model:
            self._dimension = 3072
        else:
            self._dimension = 1536

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        settings = get_settings()

        # 根据 api_base 判断 provider，选择对应的 api_key
        api_key: str | None = None
        if self._api_base and ("dashscope" in self._api_base or "aliyun" in self._api_base):
            api_key = settings.dashscope_api_key
        elif settings.openai_api_key and "openai" in self._model:
            api_key = settings.openai_api_key
        else:
            # fallback：尝试所有可用的 key
            api_key = settings.openai_api_key or settings.dashscope_api_key

        kwargs: dict = {"model": self._model, "input": texts, "encoding_format": "float"}
        if self._api_base:
            kwargs["api_base"] = self._api_base
        if api_key:
            kwargs["api_key"] = api_key

        response = await litellm.aembedding(**kwargs)
        return [item["embedding"] for item in response.data]

    @property
    def dimension(self) -> int:
        return self._dimension
