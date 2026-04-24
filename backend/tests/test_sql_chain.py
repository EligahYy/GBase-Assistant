"""Tests for SQL generation chain with mocked LLM."""
from __future__ import annotations

import pytest

from app.chains.sql_chain import run_sql_chain, stream_sql_chain
from app.protocols import ChatContext, ChatResult, ExampleRetriever, LLMClient, SchemaRetriever, StreamChunk, TableSchema


class MockLLMClient(LLMClient):
    """Mock LLM that returns predetermined responses."""

    def __init__(self, responses: list[str]):
        self.responses = responses
        self.call_count = 0
        self.last_messages: list[dict] | None = None

    async def complete(self, messages: list[dict], **kwargs) -> tuple[str, dict]:
        self.last_messages = messages
        response = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1
        return response, {"prompt": 10, "completion": 5, "total": 15, "model": "mock"}

    async def stream(self, messages: list[dict], **kwargs):
        self.last_messages = messages
        response = self.responses[self.call_count % len(self.responses)]
        self.call_count += 1
        # Yield word by word
        for word in response.split():
            yield word + " "


class MockSchemaRetriever(SchemaRetriever):
    async def retrieve(self, query: str, db_id: str) -> list[TableSchema]:
        return [
            TableSchema(
                table_name="users",
                ddl="CREATE TABLE users (id INT, name VARCHAR(20))",
                columns=["id", "name"],
            ),
        ]


class MockExampleRetriever(ExampleRetriever):
    async def retrieve(self, query: str, top_k: int = 5) -> list:
        return []


@pytest.fixture
def mock_schema_retriever():
    return MockSchemaRetriever()


@pytest.fixture
def mock_example_retriever():
    return MockExampleRetriever()


@pytest.fixture
def context():
    return ChatContext(db_id="test-db", conversation_id="conv-1", history=[])


class TestRunSQLChain:
    """Non-streaming SQL chain tests."""

    @pytest.mark.asyncio
    async def test_successful_sql_generation(self, mock_schema_retriever, mock_example_retriever, context):
        llm = MockLLMClient(['''```sql\nSELECT id FROM users\n```\n查询用户ID'''])
        result = await run_sql_chain(
            "查询所有用户ID", context, mock_schema_retriever, mock_example_retriever, llm
        )
        assert result.sql == "SELECT id FROM users"
        assert result.validation is not None
        assert result.validation.is_valid is True
        assert result.token_usage is not None

    @pytest.mark.asyncio
    async def test_prompt_contains_schema_and_rules(self, mock_schema_retriever, mock_example_retriever, context):
        llm = MockLLMClient(['''```sql\nSELECT id FROM users\n```'''])
        await run_sql_chain("查询用户", context, mock_schema_retriever, mock_example_retriever, llm)
        assert llm.last_messages is not None
        system_msg = llm.last_messages[0]["content"]
        assert "GBase 8a" in system_msg
        assert "users" in system_msg
        assert "CREATE TABLE users" in system_msg

    @pytest.mark.asyncio
    async def test_self_correction_retry(self, mock_schema_retriever, mock_example_retriever, context):
        # First response has invalid SQL (FOR UPDATE), second response is valid
        llm = MockLLMClient([
            '''```sql\nSELECT * FROM users FOR UPDATE\n```''',
            '''```sql\nSELECT * FROM users\n```''',
        ])
        result = await run_sql_chain(
            "查询用户", context, mock_schema_retriever, mock_example_retriever, llm
        )
        assert llm.call_count == 2
        assert result.validation is not None
        # Second attempt should be valid
        assert "FOR UPDATE" not in (result.sql or "")

    @pytest.mark.asyncio
    async def test_max_retries_exceeded(self, mock_schema_retriever, mock_example_retriever, context):
        # Always return invalid SQL
        llm = MockLLMClient([
            '''```sql\nSELECT * FROM users FOR UPDATE\n```''',
        ] * 5)
        result = await run_sql_chain(
            "查询用户", context, mock_schema_retriever, mock_example_retriever, llm
        )
        assert llm.call_count == 3  # MAX_RETRIES
        assert result.validation is not None
        assert result.validation.is_valid is False
        assert "FOR UPDATE" in str(result.content)

    @pytest.mark.asyncio
    async def test_no_sql_extracted(self, mock_schema_retriever, mock_example_retriever, context):
        llm = MockLLMClient(["对不起，我无法生成这个查询"])
        result = await run_sql_chain(
            "查询用户", context, mock_schema_retriever, mock_example_retriever, llm
        )
        assert result.sql is None
        assert result.validation is not None
        assert result.validation.is_valid is False


class TestStreamSQLChain:
    """Streaming SQL chain tests."""

    @pytest.mark.asyncio
    async def test_stream_yields_text_and_sql(self, mock_schema_retriever, mock_example_retriever, context):
        llm = MockLLMClient(['''```sql\nSELECT id FROM users\n```'''])
        chunks: list[StreamChunk] = []
        async for chunk in stream_sql_chain(
            "查询用户ID", context, mock_schema_retriever, mock_example_retriever, llm
        ):
            chunks.append(chunk)

        text_chunks = [c for c in chunks if c.type == "text"]
        sql_chunks = [c for c in chunks if c.type == "sql"]
        done_chunks = [c for c in chunks if c.type == "done"]

        assert len(text_chunks) > 0
        assert len(sql_chunks) == 1
        assert sql_chunks[0].content == "SELECT id FROM users"
        assert len(done_chunks) == 1

    @pytest.mark.asyncio
    async def test_stream_warning_on_invalid_sql(self, mock_schema_retriever, mock_example_retriever, context):
        llm = MockLLMClient(['''```sql\nSELECT * FROM users FOR UPDATE\n```'''])
        chunks: list[StreamChunk] = []
        async for chunk in stream_sql_chain(
            "查询用户", context, mock_schema_retriever, mock_example_retriever, llm
        ):
            chunks.append(chunk)

        warning_chunks = [c for c in chunks if c.type == "warning"]
        assert len(warning_chunks) > 0
        assert any("FOR UPDATE" in c.content for c in warning_chunks)

    @pytest.mark.asyncio
    async def test_stream_no_sql_no_warning(self, mock_schema_retriever, mock_example_retriever, context):
        llm = MockLLMClient(["无法生成SQL"])
        chunks: list[StreamChunk] = []
        async for chunk in stream_sql_chain(
            "查询用户", context, mock_schema_retriever, mock_example_retriever, llm
        ):
            chunks.append(chunk)

        sql_chunks = [c for c in chunks if c.type == "sql"]
        warning_chunks = [c for c in chunks if c.type == "warning"]
        assert len(sql_chunks) == 0
        assert len(warning_chunks) == 0
