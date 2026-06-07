"""Integration tests for v3 graph routing — verifies the graph doesn't loop infinitely."""
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolCall

from app.agents.state import AgentState


def _mock_adapter(responses: list[AIMessage]):
    """Create a mock LLM adapter that returns predefined responses in sequence."""
    call_count = [0]

    class MockAdapter:
        llm_client = None

        async def _agenerate(self, messages, **kwargs):
            idx = min(call_count[0], len(responses) - 1)
            resp = responses[idx]
            call_count[0] += 1
            from langchain_core.outputs import ChatGeneration, ChatResult
            return ChatResult(generations=[ChatGeneration(message=resp)])

    return MockAdapter()


def _tc_msg(name: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[ToolCall(name=name, args=args, id=f"call_{name}")])


def _text_msg(content: str) -> AIMessage:
    return AIMessage(content=content)


def _initial_state(msg: str, test_id: str) -> AgentState:
    return {
        "messages": [HumanMessage(content=msg)],
        "db_connection_id": None,
        "supervisor_step": 0, "supervisor_finished": False,
        "sql_step": 0, "sql_finished": False,
        "supervisor": {}, "sql": {}, "knowledge": {},
    }


@pytest.mark.asyncio
async def test_graph_finishes_greeting():
    """Graph completes for simple greeting (no delegation)."""
    mock = _mock_adapter([_text_msg("你好！")])

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=mock), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()):
        from app.agents.graph import build_graph
        graph = build_graph()
        state = _initial_state("你好", "t1")
        result = await graph.ainvoke(state, {"configurable": {"thread_id": "t1"}})
        assert result.get("final_response") is not None


@pytest.mark.asyncio
async def test_graph_finishes_with_delegation():
    """Graph completes with one delegation to SQL agent."""
    mock = _mock_adapter([
        _tc_msg("delegate_to_sql_specialist", {"query": "查询"}),
        _text_msg("SQL结果..."),
        _text_msg("SELECT * FROM orders"),
    ])

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=mock), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph._to_openai_tools", return_value=[]):
        from app.agents.graph import build_graph
        graph = build_graph()
        state = _initial_state("查询订单", "t2")
        result = await graph.ainvoke(state, {"configurable": {"thread_id": "t2"}})
        assert result.get("final_response") is not None


@pytest.mark.asyncio
async def test_graph_stops_at_iteration_limit():
    """Agent stops after MAX_ITERATIONS (doesn't loop forever)."""
    mock = _mock_adapter([_tc_msg("search_schemas", {"query": "x"})] * 20)

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=mock), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph._to_openai_tools", return_value=[]):
        from app.agents.graph import build_graph
        graph = build_graph()
        state = _initial_state("x", "t4")
        result = await graph.ainvoke(state, {"configurable": {"thread_id": "t4"}})
        step = result.get("supervisor_step", 0)
        assert step <= 16


@pytest.mark.asyncio
async def test_sql_agent_guards_no_connection():
    """SQL Agent immediately finishes with helpful message when no DB connected."""
    mock = _mock_adapter([_tc_msg("delegate_to_sql_specialist", {"query": "查询"})])

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=mock), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph._to_openai_tools", return_value=[]):
        from app.agents.graph import build_graph
        graph = build_graph()
        state = _initial_state("查询订单", "t5")
        # Explicitly set no connection
        state["db_connection_id"] = None
        result = await graph.ainvoke(state, {"configurable": {"thread_id": "t5"}})
        # Should finish with a response, not loop infinitely
        assert result.get("final_response") is not None
        response = result.get("final_response", "")
        assert "连接" in response or "数据库" in response


@pytest.mark.asyncio
async def test_max_iterations_friendly_message():
    """When max iterations hit, emits friendly message instead of silent end."""
    mock = _mock_adapter([_tc_msg("search_schemas", {"query": "x"})] * 20)

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=mock), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph._to_openai_tools", return_value=[]):
        from app.agents.graph import build_graph
        graph = build_graph()
        state = _initial_state("x", "t6")
        result = await graph.ainvoke(state, {"configurable": {"thread_id": "t6"}})
        assert result.get("final_response") is not None
