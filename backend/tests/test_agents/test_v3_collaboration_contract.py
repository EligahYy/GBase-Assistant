"""Behavior contracts for the v3 collaborative agent framework."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolCall
from langchain_core.outputs import ChatGeneration, ChatResult

from app.agents.agents.knowledge_agent import expand_knowledge_query
from app.agents.graph import _build_conversation_messages, build_graph
from app.protocols import KnowledgeChunk


class SequencedAdapter:
    """Minimal LLM adapter that records prompts and returns scripted responses."""

    def __init__(self, responses: list[AIMessage]) -> None:
        self.responses = responses
        self.calls: list[list] = []
        self.index = 0

    async def _agenerate(self, messages, **kwargs):
        self.calls.append(messages)
        response = self.responses[min(self.index, len(self.responses) - 1)]
        self.index += 1
        return ChatResult(generations=[ChatGeneration(message=response)])


def _tool_call(name: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[ToolCall(name=name, args=args, id=f"call_{name}")])


def _state(message: str, db_connection_id: str | None = "db-1") -> dict:
    return {
        "messages": [HumanMessage(content=message)],
        "db_connection_id": db_connection_id,
        "supervisor_step": 0,
        "supervisor_finished": False,
        "sql_step": 0,
        "sql_finished": False,
        "general_step": 0,
        "general_finished": False,
        "supervisor": {},
        "sql": {},
        "knowledge": {},
    }


def test_build_conversation_messages_includes_history_without_duplicate_current_message():
    history = [
        {"role": "user", "content": "查询销售额最高的部门"},
        {"role": "assistant", "content": "华东事业部最高"},
        {"role": "user", "content": "只看华东地区"},
    ]

    messages = _build_conversation_messages(history, "只看华东地区")

    assert [m.content for m in messages] == [
        "查询销售额最高的部门",
        "华东事业部最高",
        "只看华东地区",
    ]


def test_knowledge_query_expansion_matches_terms_inside_natural_language():
    expanded = expand_knowledge_query("如何创建随机分布表？")

    assert "随机分布" in expanded
    assert "DISTRIBUTED" in expanded


@pytest.mark.asyncio
async def test_sql_is_validated_before_deterministic_execution():
    adapter = SequencedAdapter(
        [
            _tool_call("delegate_to_sql_specialist", {"query": "查询订单"}),
            _tool_call("submit_sql", {"sql": "SELECT id FROM orders"}),
        ]
    )
    execution = MagicMock()
    execution.execute = AsyncMock(
        return_value={
            "columns": ["id"],
            "rows": [[1]],
            "row_count": 1,
            "execution_time_ms": 2.0,
            "truncated": False,
        }
    )

    with (
        patch("app.agents.graph.LiteLLMChatAdapter", return_value=adapter),
        patch("app.dependencies.get_llm_client", return_value=MagicMock()),
        patch("app.agents.graph.ExecuteSQLTool", return_value=execution),
    ):
        graph = build_graph(db_connection_id="db-1")
        result = await graph.ainvoke(_state("查询订单"), {"configurable": {"thread_id": "contract-sql"}})

    execution.execute.assert_awaited_once_with(sql="SELECT id FROM orders")
    assert result["sql"]["validation"]["valid"] is True
    assert result["sql"]["query_result"]["row_count"] == 1
    assert result["sql"]["generated_sql"] == "SELECT id FROM orders"


@pytest.mark.asyncio
async def test_invalid_sql_never_reaches_execution_gate():
    adapter = SequencedAdapter(
        [
            _tool_call("delegate_to_sql_specialist", {"query": "删除订单"}),
            _tool_call("submit_sql", {"sql": "DELETE FROM orders"}),
        ]
    )
    execution = MagicMock()
    execution.execute = AsyncMock()

    with (
        patch("app.agents.graph.LiteLLMChatAdapter", return_value=adapter),
        patch("app.dependencies.get_llm_client", return_value=MagicMock()),
        patch("app.agents.graph.ExecuteSQLTool", return_value=execution),
    ):
        graph = build_graph(db_connection_id="db-1")
        result = await graph.ainvoke(_state("删除订单"), {"configurable": {"thread_id": "contract-invalid"}})

    execution.execute.assert_not_awaited()
    assert result["sql"]["validation"]["valid"] is False
    assert result["sql"]["execution_error"]


@pytest.mark.asyncio
async def test_knowledge_task_retrieves_chunks_and_preserves_chapter_sources():
    adapter = SequencedAdapter(
        [
            _tool_call("delegate_to_knowledge_specialist", {"query": "如何创建随机分布表？"}),
            AIMessage(content="不指定 DISTRIBUTED BY 子句即可创建随机分布表。"),
        ]
    )
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(
        return_value=[
            KnowledgeChunk(
                content="如果不指定 DISTRIBUTED BY 和 REPLICATED，则默认创建随机分布表。",
                source="5.1.8.2.1 CREATE TABLE",
            )
        ]
    )

    with (
        patch("app.agents.graph.LiteLLMChatAdapter", return_value=adapter),
        patch("app.dependencies.get_llm_client", return_value=MagicMock()),
        patch("app.dependencies.get_knowledge_retriever", return_value=retriever),
    ):
        graph = build_graph()
        result = await graph.ainvoke(
            _state("如何创建随机分布表？", db_connection_id=None),
            {"configurable": {"thread_id": "contract-knowledge"}},
        )

    assert retriever.retrieve.await_count == 2
    assert result["knowledge"]["knowledge_sources"] == ["5.1.8.2.1 CREATE TABLE"]
    assert "随机分布表" in result["final_response"]


@pytest.mark.asyncio
async def test_supervisor_can_plan_and_run_multiple_specialists():
    adapter = SequencedAdapter(
        [
            AIMessage(
                content="",
                tool_calls=[
                    ToolCall(
                        name="delegate_to_sql_specialist",
                        args={"query": "查询订单数量"},
                        id="call_sql",
                    ),
                    ToolCall(
                        name="delegate_to_knowledge_specialist",
                        args={"query": "解释分布表"},
                        id="call_knowledge",
                    ),
                ],
            ),
            _tool_call("submit_sql", {"sql": "SELECT COUNT(*) AS cnt FROM orders"}),
            AIMessage(content="分布表会按分布键分散存储。[manual]"),
        ]
    )
    execution = MagicMock()
    execution.execute = AsyncMock(
        return_value={
            "columns": ["cnt"],
            "rows": [[3]],
            "row_count": 1,
            "execution_time_ms": 1.0,
            "truncated": False,
        }
    )
    retriever = MagicMock()
    retriever.retrieve = AsyncMock(return_value=[])

    with (
        patch("app.agents.graph.LiteLLMChatAdapter", return_value=adapter),
        patch("app.dependencies.get_llm_client", return_value=MagicMock()),
        patch("app.agents.graph.ExecuteSQLTool", return_value=execution),
        patch("app.dependencies.get_knowledge_retriever", return_value=retriever),
    ):
        graph = build_graph(db_connection_id="db-1")
        result = await graph.ainvoke(
            _state("查询订单数量，并解释分布表"),
            {"configurable": {"thread_id": "contract-collaboration"}},
        )

    completed = result["supervisor"]["completed_tasks"]
    assert [task["type"] for task in completed] == ["sql", "knowledge"]
    assert result["sql"]["query_result"]["row_count"] == 1


def test_build_graph_applies_user_selected_model():
    with (
        patch("app.agents.graph.LiteLLMChatAdapter", side_effect=lambda client: client),
        patch("app.dependencies.get_llm_client", return_value=MagicMock()) as get_client,
    ):
        build_graph(db_connection_id="db-1", model="openai/gpt-4o")

    assert get_client.call_count == 4
    assert all(call.kwargs["model"] == "openai/gpt-4o" for call in get_client.call_args_list)
