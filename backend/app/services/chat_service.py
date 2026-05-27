"""聊天请求编排服务。"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.chains.intent import classify_intent
from app.chains.qa_chain import run_qa_chain, stream_qa_chain
from app.chains.sql_chain import run_sql_chain, stream_sql_chain
from app.dependencies import get_llm_client
from app.llm.client import AllModelsFailedError
from app.llm.prompts import build_general_prompt
from app.protocols import (
    ChatResult,
    ExampleRetriever,
    KnowledgeRetriever,
    LLMClient,
    SchemaRetriever,
    StreamChunk,
)
from app.schemas.chat import ChatRequest, ChatResponse, MessageResponse
from app.services.conversation_service import build_context, get_or_create_conversation, save_messages
from app.services.sql_execution_service import execute_sql_for_connection, format_query_result_summary
from app.services.summary_service import trigger_summary_generation

logger = logging.getLogger(__name__)


class _TestingLLMClient:
    """测试模式 LLM：仅用于聊天 API，避免集成测试触发真实网络请求。"""

    def __init__(self, task_type: str = "general") -> None:
        self.task_type = task_type

    async def complete(self, messages: list[dict], **kwargs) -> tuple[str, dict]:
        if self.task_type == "intent_classification":
            user_message = messages[-1].get("content", "") if messages else ""
            if any(keyword in user_message for keyword in ("查询", "统计", "列出", "分析")):
                content = '{"intent": "sql"}'
            elif any(keyword in user_message for keyword in ("支持", "怎么", "什么", "错误")):
                content = '{"intent": "qa"}'
            else:
                content = '{"intent": "general"}'
        elif self.task_type == "sql_generation":
            content = "```sql\nSELECT 1;\n```\n测试模式 SQL。"
        else:
            content = "测试模式回复。"

        return content, {"prompt": 0, "completion": 0, "total": 0, "model": "testing"}

    async def stream(self, messages: list[dict], **kwargs) -> AsyncIterator[str]:
        content, _ = await self.complete(messages, **kwargs)
        yield content


class ChatService:
    """编排一次聊天请求，保持 API 层轻量。"""

    def __init__(
        self,
        db: AsyncSession,
        schema_retriever: SchemaRetriever,
        example_retriever: ExampleRetriever,
        knowledge_retriever: KnowledgeRetriever,
    ) -> None:
        self._db = db
        self._schema_retriever = schema_retriever
        self._example_retriever = example_retriever
        self._knowledge_retriever = knowledge_retriever

    async def run(self, request: ChatRequest) -> ChatResponse:
        """执行非流式聊天请求。"""
        conv, intent, llm_client, context = await self._prepare(request)
        chat_result = await self._run_chain(request, intent, llm_client, context)

        if self._should_execute_sql(intent, chat_result, conv.db_connection_id):
            query_result = await execute_sql_for_connection(
                self._db, conv.db_connection_id or "", chat_result.sql or ""
            )
            if query_result and not query_result.get("error"):
                chat_result.content += format_query_result_summary(query_result)
            elif query_result and query_result.get("error"):
                chat_result.content += f"\n\n⚠️ 执行失败：{query_result['error']}"

        _, assistant_msg = await save_messages(
            self._db,
            conv,
            user_content=request.message,
            result_content=chat_result.content,
            message_type=chat_result.message_type,
            sql_generated=chat_result.sql,
            sql_validated=chat_result.validation.is_valid if chat_result.validation else None,
            token_usage=chat_result.token_usage,
        )
        asyncio.create_task(trigger_summary_generation(conv.id, request.model))

        return ChatResponse(
            conversation_id=conv.id,
            message=MessageResponse.from_orm_model(assistant_msg),
        )

    async def stream(self, request: ChatRequest) -> tuple[str, AsyncIterator[str]]:
        """准备流式聊天请求，返回 conversation_id 和 SSE 迭代器。"""
        conv, intent, llm_client, context = await self._prepare(request)

        async def event_generator() -> AsyncIterator[str]:
            full_content = ""
            sql_content = None
            sql_validated = None
            token_usage = None

            try:
                stream = self._select_stream(request, intent, llm_client, context)
                async for chunk in stream:
                    if chunk.type == "text":
                        full_content += chunk.content
                    elif chunk.type == "sql":
                        sql_content = chunk.content
                    elif chunk.type == "warning":
                        full_content += f"\n\n{chunk.content}"
                        if sql_content and "⚠️" in chunk.content:
                            sql_validated = False
                    elif chunk.type == "done":
                        token_usage = chunk.token_usage
                    yield chunk.to_sse()

                if sql_content is not None and sql_validated is None:
                    sql_validated = True

                if intent == "sql" and sql_content and sql_validated and conv.db_connection_id:
                    query_result = await execute_sql_for_connection(self._db, conv.db_connection_id, sql_content)
                    if query_result and not query_result.get("error"):
                        yield StreamChunk(type="result", content=json.dumps(query_result, ensure_ascii=False)).to_sse()
                        full_content += format_query_result_summary(query_result)
                    elif query_result and query_result.get("error"):
                        yield StreamChunk(type="result_error", content=query_result["error"]).to_sse()
                        full_content += f"\n\n⚠️ 执行失败：{query_result['error']}"

            except AllModelsFailedError as e:
                logger.warning("流式模型调用失败: %s", e.user_message)
                yield StreamChunk(type="error", content=e.user_message).to_sse()
                return
            except Exception as e:
                logger.error("流式生成错误: %s", e)
                yield StreamChunk(type="error", content=f"生成失败：{e!s}").to_sse()
                return

            try:
                user_msg, assistant_msg = await save_messages(
                    self._db,
                    conv,
                    user_content=request.message,
                    result_content=full_content,
                    message_type=intent,
                    sql_generated=sql_content,
                    sql_validated=sql_validated,
                    token_usage=token_usage,
                )
                yield StreamChunk(
                    type="message_ids",
                    content=json.dumps(
                        {
                            "user_message_id": user_msg.id,
                            "assistant_message_id": assistant_msg.id,
                        },
                        ensure_ascii=False,
                    ),
                ).to_sse()
                asyncio.create_task(trigger_summary_generation(conv.id, request.model))
            except Exception as e:
                logger.error("保存消息失败: %s", e)

        return conv.id, event_generator()

    async def _prepare(self, request: ChatRequest):
        intent_client: LLMClient = self._get_llm_client(request.model, task_type="intent_classification")
        conv = await get_or_create_conversation(
            self._db,
            request.conversation_id,
            request.db_connection_id,
            request.model,
        )
        context = await build_context(self._db, conv)
        intent = await classify_intent(request.message, intent_client)
        logger.info("意图分类: %s | 消息: %.50s", intent, request.message)

        task_type = "sql_generation" if intent == "sql" else ("knowledge_qa" if intent == "qa" else "general")
        return conv, intent, self._get_llm_client(request.model, task_type=task_type), context

    async def _run_chain(
        self,
        request: ChatRequest,
        intent: str,
        llm_client: LLMClient,
        context,
    ) -> ChatResult:
        if intent == "sql":
            return await run_sql_chain(
                request.message,
                context,
                self._schema_retriever,
                self._example_retriever,
                llm_client,
            )
        if intent == "qa":
            return await run_qa_chain(request.message, context, self._knowledge_retriever, llm_client)

        content, token_usage = await llm_client.complete(build_general_prompt(request.message, context.history))
        return ChatResult(content=content, message_type="general", token_usage=token_usage)

    def _select_stream(
        self,
        request: ChatRequest,
        intent: str,
        llm_client: LLMClient,
        context,
    ) -> AsyncIterator[StreamChunk]:
        if intent == "sql":
            return stream_sql_chain(
                request.message,
                context,
                self._schema_retriever,
                self._example_retriever,
                llm_client,
            )
        if intent == "qa":
            return stream_qa_chain(request.message, context, self._knowledge_retriever, llm_client)
        return self._general_stream(request, llm_client, context)

    async def _general_stream(
        self,
        request: ChatRequest,
        llm_client: LLMClient,
        context,
    ) -> AsyncIterator[StreamChunk]:
        async for token in llm_client.stream(build_general_prompt(request.message, context.history)):
            yield StreamChunk(type="text", content=token)
        yield StreamChunk(type="done", content="", token_usage={})

    @staticmethod
    def _should_execute_sql(intent: str, chat_result: ChatResult, db_connection_id: str | None) -> bool:
        return bool(
            intent == "sql"
            and chat_result.sql
            and chat_result.validation
            and chat_result.validation.is_valid
            and db_connection_id
        )

    @staticmethod
    def _get_llm_client(model: str | None, task_type: str) -> LLMClient:
        if os.getenv("TESTING"):
            return _TestingLLMClient(task_type=task_type)  # type: ignore[return-value]
        return get_llm_client(model, task_type=task_type)
