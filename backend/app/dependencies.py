"""FastAPI dependency injection bindings.
Upgrade path: Phase 3 swap File* implementations for Qdrant* here only.
"""
from __future__ import annotations

from functools import lru_cache

from app.config import get_settings
from app.knowledge.loader import FileExampleRetriever, FileKnowledgeRetriever
from app.llm.client import LiteLLMClientImpl
from app.protocols import ExampleRetriever, KnowledgeRetriever, LLMClient


@lru_cache
def _get_example_retriever() -> FileExampleRetriever:
    return FileExampleRetriever()


@lru_cache
def _get_knowledge_retriever() -> FileKnowledgeRetriever:
    return FileKnowledgeRetriever()


def get_example_retriever() -> ExampleRetriever:
    """Phase 1: file loader -> Phase 3: QdrantExampleRetriever"""
    return _get_example_retriever()


def get_knowledge_retriever() -> KnowledgeRetriever:
    """Phase 1: keyword match -> Phase 3: QdrantKnowledgeRetriever"""
    return _get_knowledge_retriever()


def get_llm_client(model: str | None = None, task_type: str = "general") -> LLMClient:
    """Create LLM client per request, with optional model override and task type."""
    return LiteLLMClientImpl(model=model, task_type=task_type)
