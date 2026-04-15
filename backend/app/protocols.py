"""
核心接口定义（升级缝）。
所有模块依赖此文件中的 Protocol，不依赖具体实现。
升级时只替换 dependencies.py 中的绑定，调用方代码不变。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import AsyncIterator, Protocol, runtime_checkable


@dataclass
class TableSchema:
    table_name: str
    ddl: str
    description: str = ""


@dataclass
class SQLExample:
    question: str
    sql: str
    tables: list[str] = field(default_factory=list)
    pattern: str = ""
    difficulty: str = "medium"


@dataclass
class KnowledgeChunk:
    content: str
    source: str
    category: str = ""


@dataclass
class ChatContext:
    db_id: str | None = None
    conversation_id: str | None = None
    history: list[dict] = field(default_factory=list)
    retry_count: int = 0


@dataclass
class StreamChunk:
    type: str  # "text" | "sql" | "done" | "error"
    content: str = ""
    token_usage: dict | None = None

    def to_sse(self) -> str:
        data = {"type": self.type, "content": self.content}
        if self.token_usage:
            data["token_usage"] = self.token_usage
        return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@dataclass
class ValidationResult:
    is_valid: bool
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    corrected_sql: str | None = None


@dataclass
class ChatResult:
    content: str
    message_type: str  # "sql" | "qa" | "general"
    sql: str | None = None
    sources: list[dict] = field(default_factory=list)
    token_usage: dict | None = None
    validation: ValidationResult | None = None


@runtime_checkable
class SchemaRetriever(Protocol):
    """Schema 检索接口。Phase 1: 全量返回 → Phase 3: Qdrant 向量检索"""

    async def retrieve(self, query: str, db_id: str) -> list[TableSchema]:
        """根据查询和 db_id 检索相关表 schema"""
        ...


@runtime_checkable
class ExampleRetriever(Protocol):
    """Few-shot 示例检索接口。Phase 1: 文件全量加载 → Phase 3: Qdrant 向量检索"""

    async def retrieve(self, query: str, top_k: int = 5) -> list[SQLExample]:
        """根据查询检索最相关的 SQL 示例"""
        ...


@runtime_checkable
class KnowledgeRetriever(Protocol):
    """知识库检索接口。Phase 1: 关键词匹配 JSON → Phase 3: RAG 向量检索"""

    async def retrieve(self, query: str, category: str | None = None) -> list[KnowledgeChunk]:
        """根据查询检索知识库内容"""
        ...


@runtime_checkable
class LLMClient(Protocol):
    """LLM 调用接口。Phase 1: 单模型 LiteLLM → Phase 2: 多模型 fallback"""

    async def complete(self, messages: list[dict], **kwargs) -> tuple[str, dict]:
        """同步生成，返回 (content, token_usage)"""
        ...

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        """流式生成，yield token chunks"""
        ...
