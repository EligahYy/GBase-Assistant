"""
FastAPI 依赖注入绑定。
升级路径：Phase 3 时只改此文件，将 File* 实现替换为 Qdrant* 实现。
"""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.knowledge.loader import FileExampleRetriever, FileKnowledgeRetriever
from app.llm.client import LiteLLMClientImpl
from app.protocols import ExampleRetriever, KnowledgeRetriever, LLMClient

# ── 单例实例（进程级缓存）────────────────────────────────────────────────────────

@lru_cache
def _get_example_retriever() -> FileExampleRetriever:
    return FileExampleRetriever()


@lru_cache
def _get_knowledge_retriever() -> FileKnowledgeRetriever:
    return FileKnowledgeRetriever()


# ── FastAPI 依赖函数 ──────────────────────────────────────────────────────────────

def get_example_retriever() -> ExampleRetriever:
    """Phase 1: 文件加载 → Phase 3: QdrantExampleRetriever"""
    return _get_example_retriever()


def get_knowledge_retriever() -> KnowledgeRetriever:
    """Phase 1: 关键词匹配 → Phase 3: QdrantKnowledgeRetriever"""
    return _get_knowledge_retriever()


def get_llm_client(model: str | None = None) -> LLMClient:
    """每次请求可按用户指定 model 创建（不缓存，model 可变）。"""
    settings = get_settings()
    return LiteLLMClientImpl(model=model or settings.default_model)
