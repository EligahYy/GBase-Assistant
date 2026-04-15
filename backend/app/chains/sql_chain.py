"""
SQL 生成链：NL → Schema 检索 → Few-shot 检索 → LLM 生成 → 验证 → 自纠错。
遵循 Protocol 驱动设计：所有依赖通过参数注入，函数为纯函数语义。
"""
from __future__ import annotations

import logging
from typing import AsyncIterator

from app.knowledge.loader import load_dialect_rules
from app.llm.prompts import build_sql_correction_prompt, build_sql_prompt
from app.protocols import (
    ChatContext,
    ChatResult,
    ExampleRetriever,
    LLMClient,
    SchemaRetriever,
    StreamChunk,
    ValidationResult,
)
from app.sql.validator import extract_sql_from_markdown, validate_sql

logger = logging.getLogger(__name__)

MAX_RETRIES = 3


async def run_sql_chain(
    message: str,
    context: ChatContext,
    schema_retriever: SchemaRetriever,
    example_retriever: ExampleRetriever,
    llm_client: LLMClient,
) -> ChatResult:
    """
    SQL 生成链（非流式）。
    返回 ChatResult，包含完整内容、提取出的 SQL、验证结果。
    """
    dialect_rules = load_dialect_rules()
    schemas = await schema_retriever.retrieve(message, context.db_id or "")
    examples = await example_retriever.retrieve(message, top_k=5)

    messages = build_sql_prompt(message, dialect_rules, schemas, examples, context.history)

    for attempt in range(MAX_RETRIES):
        content, token_usage = await llm_client.complete(messages, temperature=0.1)
        sql = extract_sql_from_markdown(content)

        if not sql:
            # LLM 没有输出 SQL 代码块，直接返回内容（可能是无法生成的情况）
            logger.warning("SQL 链第 %d 次尝试未提取到 SQL", attempt + 1)
            return ChatResult(
                content=content,
                message_type="sql",
                sql=None,
                token_usage=token_usage,
                validation=ValidationResult(is_valid=False, errors=["未能从回答中提取 SQL"]),
            )

        validation = validate_sql(sql, schemas if schemas and schemas[0].table_name != "__all__" else None)

        if validation.is_valid:
            logger.info("SQL 链第 %d 次尝试验证通过", attempt + 1)
            return ChatResult(
                content=content,
                message_type="sql",
                sql=sql,
                token_usage=token_usage,
                validation=validation,
            )

        # 验证失败，自纠错
        logger.warning("SQL 链第 %d 次尝试验证失败: %s", attempt + 1, validation.errors)
        if attempt < MAX_RETRIES - 1:
            messages = build_sql_correction_prompt(message, sql, validation.errors, messages)
        else:
            # 最后一次失败，仍返回结果但标记无效
            return ChatResult(
                content=content + f"\n\n⚠️ 注意：以上 SQL 存在以下问题：\n" + "\n".join(f"- {e}" for e in validation.errors),
                message_type="sql",
                sql=sql,
                token_usage=token_usage,
                validation=validation,
            )

    # 不应到达此处
    return ChatResult(content="SQL 生成失败", message_type="sql")


async def stream_sql_chain(
    message: str,
    context: ChatContext,
    schema_retriever: SchemaRetriever,
    example_retriever: ExampleRetriever,
    llm_client: LLMClient,
) -> AsyncIterator[StreamChunk]:
    """
    SQL 生成链（流式版本）。
    先流式输出 LLM token，完成后异步验证并追加结果。
    """
    dialect_rules = load_dialect_rules()
    schemas = await schema_retriever.retrieve(message, context.db_id or "")
    examples = await example_retriever.retrieve(message, top_k=5)

    messages = build_sql_prompt(message, dialect_rules, schemas, examples, context.history)

    full_content = ""
    token_usage: dict = {}

    # 流式输出 LLM 内容
    async for token in llm_client.stream(messages, temperature=0.1):
        full_content += token
        yield StreamChunk(type="text", content=token)

    # 提取 SQL 并验证
    sql = extract_sql_from_markdown(full_content)
    if sql:
        validation = validate_sql(sql, schemas if schemas and schemas[0].table_name != "__all__" else None)
        yield StreamChunk(type="sql", content=sql)
        if not validation.is_valid:
            warnings_text = "\n".join(f"⚠️ {e}" for e in validation.errors)
            yield StreamChunk(type="warning", content=warnings_text)
        elif validation.warnings:
            warnings_text = "\n".join(f"💡 {w}" for w in validation.warnings)
            yield StreamChunk(type="warning", content=warnings_text)

    yield StreamChunk(type="done", content="", token_usage=token_usage)
