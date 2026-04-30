"""本地 Bge-M3 Embedding 实现（sentence-transformers）。"""

from __future__ import annotations

import asyncio
import logging
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger(__name__)

_pool = ThreadPoolExecutor(max_workers=2)


class BgeM3Embedder:
    """基于 sentence-transformers 的本地 bge-m3 embedder。

    首次实例化时会自动下载模型（约 2.3GB）。
    建议在启动时预加载，避免首次请求时阻塞。
    """

    def __init__(self, model_name: str = "BAAI/bge-m3", device: str = "cpu") -> None:
        self._model_name = model_name
        self._device = device
        self._model = None
        self._dimension = 1024  # bge-m3 默认维度

    def _load(self):
        if self._model is not None:
            return self._model
        import os

        from sentence_transformers import SentenceTransformer

        # 国内网络环境下使用 HF 镜像加速下载
        if not os.getenv("HF_ENDPOINT"):
            os.environ["HF_ENDPOINT"] = "https://hf-mirror.com"
            logger.info("使用 Hugging Face 镜像: %s", os.environ["HF_ENDPOINT"])

        logger.info("Loading local embedding model: %s on %s", self._model_name, self._device)
        self._model = SentenceTransformer(self._model_name, device=self._device)
        self._dimension = self._model.get_sentence_embedding_dimension()
        logger.info("Model loaded. dimension=%d", self._dimension)
        return self._model

    async def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        loop = asyncio.get_event_loop()
        embeddings = await loop.run_in_executor(_pool, lambda: model.encode(texts, normalize_embeddings=True))
        return embeddings.tolist()

    @property
    def dimension(self) -> int:
        return self._dimension
