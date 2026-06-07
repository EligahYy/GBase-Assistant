"""Behavior contracts for the v3.2 Unified Agent framework."""

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


def _final_answer(answer: str, sources: list[str] | None = None) -> AIMessage:
    return AIMessage(
        content="",
        tool_calls=[ToolCall(name="final_answer", args={"answer": answer, "sources": sources or []}, id="call_fa")],
    )


def _state(message: str, db_connection_id: str | None = "db-1") -> dict:
    return {
        "messages": [HumanMessage(content=message)],
        "db_connection_id": db_connection_id,
        "agent_step": 0,
        "agent_finished": False,
        "sql": {},
        "knowledge": {},
    }


def _mock_tools_for_test(tool_names: list[str]):
    """Return a minimal tool list containing only mocked tools for the given names.

    Each tool is a MagicMock with .name, .to_openai_schema(), .execute(), and .format_result().
    """
    from app.agents.tools.sql_tools import ExecuteSQLTool, SubmitSQLTool
    from app.agents.tools.knowledge_tools import SearchKnowledgeTool

    TOOL_CLASSES = {
        "submit_sql": SubmitSQLTool,
        "search_knowledge": SearchKnowledgeTool,
        "final_answer": None,  # handled separately — needs special execute
    }

    tools = []
    for name in tool_names:
        if name == "final_answer":
            from app.agents.agents.unified_agent import FinalAnswerTool
            tools.append(FinalAnswerTool())
        elif name in TOOL_CLASSES:
            cls = TOOL_CLASSES[name]
            if cls:
                tools.append(cls())
    return tools


# ── Helpers ────────────────────────────────────────────────────────────────────


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


# ── v3.2 Unified Agent Contracts ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_sql_is_validated_before_deterministic_execution():
    """SQL submit_sql → validation gate → execution gate (deterministic, unchanged from v3.1)."""
    from app.agents.tools.sql_tools import SubmitSQLTool

    adapter = SequencedAdapter(
        [
            _tool_call("submit_sql", {"sql": "SELECT id FROM orders"}),
            _final_answer("查询完成：3 行数据"),
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
        patch("app.agents.graph.get_unified_agent_tools", return_value=[SubmitSQLTool()]),
    ):
        graph = build_graph(db_connection_id="db-1")
        result = await graph.ainvoke(_state("查询订单"), {"configurable": {"thread_id": "contract-sql"}})

    execution.execute.assert_awaited_once_with(sql="SELECT id FROM orders")
    assert result["sql"]["validation"]["valid"] is True
    assert result["sql"]["query_result"]["row_count"] == 1
    assert result["sql"]["generated_sql"] == "SELECT id FROM orders"


@pytest.mark.asyncio
async def test_invalid_sql_never_reaches_execution_gate():
    """DELETE FROM orders → validation fails → never reaches execute."""
    from app.agents.tools.sql_tools import SubmitSQLTool

    adapter = SequencedAdapter(
        [
            _tool_call("submit_sql", {"sql": "DELETE FROM orders"}),
            _final_answer("无法执行 DELETE 操作，GBase 8a 只支持只读查询。"),
        ]
    )
    execution = MagicMock()
    execution.execute = AsyncMock()

    with (
        patch("app.agents.graph.LiteLLMChatAdapter", return_value=adapter),
        patch("app.dependencies.get_llm_client", return_value=MagicMock()),
        patch("app.agents.graph.ExecuteSQLTool", return_value=execution),
        patch("app.agents.graph.get_unified_agent_tools", return_value=[SubmitSQLTool()]),
    ):
        graph = build_graph(db_connection_id="db-1")
        result = await graph.ainvoke(_state("删除订单"), {"configurable": {"thread_id": "contract-invalid"}})

    execution.execute.assert_not_awaited()
    assert result["sql"]["validation"]["valid"] is False
    assert result["sql"]["execution_error"]


@pytest.mark.asyncio
async def test_knowledge_search_returns_chunks_with_status():
    """search_knowledge → agent reads chunks + status → final_answer with sources."""
    from app.agents.tools.knowledge_tools import SearchKnowledgeTool

    adapter = SequencedAdapter(
        [
            _tool_call("search_knowledge", {"query": "如何创建随机分布表？"}),
            _final_answer(
                "不指定 DISTRIBUTED BY 子句即可创建随机分布表。",
                sources=["5.1.8.2.1 CREATE TABLE"],
            ),
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
        patch("app.agents.graph.get_unified_agent_tools", return_value=[SearchKnowledgeTool()]),
    ):
        graph = build_graph()
        result = await graph.ainvoke(
            _state("如何创建随机分布表？", db_connection_id=None),
            {"configurable": {"thread_id": "contract-knowledge"}},
        )

    assert retriever.retrieve.await_count >= 1
    assert result["final_response"] is not None
    assert "随机分布表" in result["final_response"]


@pytest.mark.asyncio
async def test_unified_agent_handles_multi_intent_query():
    """'查询订单数量，并解释分布表' → agent searches schema AND knowledge → final_answer."""
    from app.agents.tools.knowledge_tools import SearchKnowledgeTool
    from app.agents.tools.sql_tools import SubmitSQLTool

    adapter = SequencedAdapter(
        [
            AIMessage(
                content="",
                tool_calls=[
                    ToolCall(name="submit_sql", args={"sql": "SELECT COUNT(*) AS cnt FROM orders"}, id="call_sql"),
                    ToolCall(name="search_knowledge", args={"query": "分布表"}, id="call_know"),
                ],
            ),
            _final_answer(
                "查询结果：共 3 条订单。\n\n分布表按分布键分散存储。[manual]",
                sources=["manual"],
            ),
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
    retriever.retrieve = AsyncMock(return_value=[
        KnowledgeChunk(content="分布表...", source="manual"),
    ])

    with (
        patch("app.agents.graph.LiteLLMChatAdapter", return_value=adapter),
        patch("app.dependencies.get_llm_client", return_value=MagicMock()),
        patch("app.agents.graph.ExecuteSQLTool", return_value=execution),
        patch("app.dependencies.get_knowledge_retriever", return_value=retriever),
        patch("app.agents.graph.get_unified_agent_tools", return_value=[SubmitSQLTool(), SearchKnowledgeTool()]),
    ):
        graph = build_graph(db_connection_id="db-1")
        result = await graph.ainvoke(
            _state("查询订单数量，并解释分布表"),
            {"configurable": {"thread_id": "contract-multi"}},
        )

    assert result["sql"]["query_result"]["row_count"] == 1
    assert result["final_response"] is not None


@pytest.mark.asyncio
async def test_final_answer_terminates_agent():
    """Agent calling final_answer → agent_finished=True, graph ends."""
    adapter = SequencedAdapter([_final_answer("你好！有什么可以帮你的？")])

    with (
        patch("app.agents.graph.LiteLLMChatAdapter", return_value=adapter),
        patch("app.dependencies.get_llm_client", return_value=MagicMock()),
        patch("app.agents.graph.get_unified_agent_tools", return_value=[]),
    ):
        graph = build_graph()
        result = await graph.ainvoke(
            _state("你好", db_connection_id=None),
            {"configurable": {"thread_id": "contract-fa"}},
        )

    assert result["agent_finished"] is True
    assert result["final_response"] == "你好！有什么可以帮你的？"


def test_build_graph_applies_user_selected_model():
    """build_graph(model='openai/gpt-4o') passes model through to LLM client."""
    with (
        patch("app.agents.graph.LiteLLMChatAdapter", side_effect=lambda client: client),
        patch("app.dependencies.get_llm_client", return_value=MagicMock()) as get_client,
        patch("app.agents.graph.get_unified_agent_tools", return_value=[]),
    ):
        build_graph(db_connection_id="db-1", model="openai/gpt-4o")

    # v3.2: single LLM client for unified agent (was 4 in v3.1)
    assert get_client.call_count == 1
    assert get_client.call_args.kwargs["model"] == "openai/gpt-4o"
