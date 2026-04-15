"""GBase 8a 知识问答链：知识库检索 → LLM 生成回答。"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from app.llm.prompts import build_qa_prompt
from app.protocols import ChatContext, ChatResult, KnowledgeRetriever, LLMClient, StreamChunk

logger = logging.getLogger(__name__)


async def run_qa_chain(
    message: str,
    context: ChatContext,
    knowledge_retriever: KnowledgeRetriever,
    llm_client: LLMClient,
) -> ChatResult:
    """知识问答链（非流式）。"""
    chunks = await knowledge_retriever.retrieve(message)
    messages = build_qa_prompt(message, chunks, context.history)
    content, token_usage = await llm_client.complete(messages, temperature=0.3)

    sources = [{"content": c.content[:100] + "...", "source": c.source} for c in chunks]

    return ChatResult(
        content=content,
        message_type="qa",
        sources=sources,
        token_usage=token_usage,
    )


async def stream_qa_chain(
    message: str,
    context: ChatContext,
    knowledge_retriever: KnowledgeRetriever,
    llm_client: LLMClient,
) -> AsyncIterator[StreamChunk]:
    """知识问答链（流式）。"""
    chunks = await knowledge_retriever.retrieve(message)
    messages = build_qa_prompt(message, chunks, context.history)

    async for token in llm_client.stream(messages, temperature=0.3):
        yield StreamChunk(type="text", content=token)

    if chunks:
        sources_text = "\n".join(f"- {c.source}" for c in chunks)
        yield StreamChunk(type="sources", content=sources_text)

    yield StreamChunk(type="done", content="")
