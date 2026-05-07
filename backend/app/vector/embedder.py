"""Embedding 模型管理：根据配置创建对应的 Embedder 实现。"""

from __future__ import annotations

import logging

from app.config import get_settings
from app.protocols import Embedder
from app.vector.embedders.litellm import LiteLLMEmbedder
from app.vector.embedders.local import BgeM3Embedder

logger = logging.getLogger(__name__)

_embedder_instance: Embedder | None = None


class _FakeEmbedder:
    """测试用的假 Embedder：返回固定维度的随机向量，不依赖外部模型。"""

    def __init__(self, dimension: int = 1024) -> None:
        self._dimension = dimension

    async def embed(self, texts: list[str]) -> list[list[float]]:
        import random

        # 使用固定种子保证可重复性
        rng = random.Random(42)
        return [[rng.random() for _ in range(self._dimension)] for _ in texts]

    @property
    def dimension(self) -> int:
        return self._dimension


def get_embedder() -> Embedder:
    """根据 models.yaml 配置创建 Embedder（单例）。"""
    global _embedder_instance
    if _embedder_instance is not None:
        return _embedder_instance

    import os

    if os.getenv("TESTING"):
        _embedder_instance = _FakeEmbedder()
        logger.info("Embedder: fake (testing mode)")
        return _embedder_instance

    settings = get_settings()
    cfg = settings.models_config.get("embedding", {})
    provider = cfg.get("provider", "local")

    if provider == "local":
        local_cfg = cfg.get("local", {})
        _embedder_instance = BgeM3Embedder(
            model_name=local_cfg.get("model", "BAAI/bge-m3"),
            device=local_cfg.get("device", "cpu"),
        )
        logger.info("Embedder: local BgeM3 (%s)", local_cfg.get("model", "BAAI/bge-m3"))
    elif provider == "litellm":
        litellm_cfg = cfg.get("litellm", {})
        _embedder_instance = LiteLLMEmbedder(
            model=litellm_cfg.get("model", "openai/text-embedding-3-small"),
            api_base=litellm_cfg.get("api_base"),
            dimension=cfg.get("dimension"),
        )
        logger.info(
            "Embedder: LiteLLM (%s, dim=%d)",
            litellm_cfg.get("model", "openai/text-embedding-3-small"),
            _embedder_instance.dimension,
        )
    else:
        raise ValueError(f"Unknown embedder provider: {provider}")

    return _embedder_instance
