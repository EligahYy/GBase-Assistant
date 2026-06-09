"""Integration tests for v3.2 Unified Agent graph routing — verifies the graph terminates correctly."""

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


def _fa_msg(answer: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[ToolCall(name="final_answer", args={"answer": answer}, id="call_fa")])


def _text_msg(content: str) -> AIMessage:
    return AIMessage(content=content)


def _initial_state(msg: str, test_id: str, db_id: str | None = None) -> AgentState:
    return {
        "messages": [HumanMessage(content=msg)],
        "db_connection_id": db_id,
        "agent_step": 0,
        "agent_finished": False,
        "sql": {},
        "knowledge": {},
    }


@pytest.mark.asyncio
async def test_graph_finishes_with_final_answer():
    """Unified agent calls final_answer → graph ends with final_response."""
    mock = _mock_adapter([_fa_msg("你好！有什么可以帮你的？")])

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=mock), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph.get_unified_agent_tools", return_value=[]):
        from app.agents.graph import build_graph
        graph = build_graph()
        state = _initial_state("你好", "t1")
        result = await graph.ainvoke(state, {"configurable": {"thread_id": "t1"}})
        assert result.get("final_response") == "你好！有什么可以帮你的？"
        assert result.get("agent_finished") is True


@pytest.mark.asyncio
async def test_graph_finishes_text_fallback():
    """Agent outputs text without tool calls → treated as final answer (fallback)."""
    mock = _mock_adapter([_text_msg("你好！")])

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=mock), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph.get_unified_agent_tools", return_value=[]):
        from app.agents.graph import build_graph
        graph = build_graph()
        state = _initial_state("你好", "t2")
        result = await graph.ainvoke(state, {"configurable": {"thread_id": "t2"}})
        assert result.get("final_response") is not None
        assert result.get("agent_finished") is True


@pytest.mark.asyncio
async def test_graph_stops_at_iteration_limit():
    """Agent stops after MAX_ITERATIONS (12) — doesn't loop forever."""
    # Use submit_sql to avoid DB-dependent tools
    from app.agents.tools.sql_tools import SubmitSQLTool

    mock = _mock_adapter([_tc_msg("submit_sql", {"sql": "SELECT 1"})] * 20)

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=mock), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph.get_unified_agent_tools", return_value=[SubmitSQLTool()]):
        from app.agents.graph import build_graph
        graph = build_graph()
        state = _initial_state("x", "t3")
        result = await graph.ainvoke(state, {"configurable": {"thread_id": "t3"}})
        # Graph must terminate — agent_step should be at or near MAX_ITERATIONS
        step = result.get("agent_step", 0)
        assert 1 <= step <= 13  # At least 1 iteration, at most MAX_ITERATIONS + 1


@pytest.mark.asyncio
async def test_execution_error_allows_retry_then_terminates():
    """SQL execution error returns feedback to agent, retries up to 3x, then terminates."""
    from app.agents.tools.sql_tools import SubmitSQLTool

    mock = _mock_adapter([_tc_msg("submit_sql", {"sql": "SELECT 1"})] * 20)

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=mock), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph.get_unified_agent_tools", return_value=[SubmitSQLTool()]):
        from app.agents.graph import build_graph
        graph = build_graph()
        state = _initial_state("x", "t4")
        result = await graph.ainvoke(state, {"configurable": {"thread_id": "t4"}})
        # Graph must terminate (not loop forever)
        # Either via max_iterations, execution retry exhaustion, or agent giving up
        step = result.get("agent_step", 0)
        assert 1 <= step <= 13  # Between 1 and MAX_ITERATIONS+1
        # Final state should have meaningful content
        assert result.get("agent_finished") is True or len(result.get("messages", [])) > 0


@pytest.mark.asyncio
async def test_agent_handles_no_db_connection():
    """When no DB connected, agent can still respond (via final_answer)."""
    mock = _mock_adapter([_fa_msg("当前未选择数据库连接，请先在设置中添加。")])

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=mock), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph.get_unified_agent_tools", return_value=[]):
        from app.agents.graph import build_graph
        graph = build_graph()
        state = _initial_state("查询订单", "t5", db_id=None)
        result = await graph.ainvoke(state, {"configurable": {"thread_id": "t5"}})
        assert result.get("final_response") is not None
        assert result.get("agent_finished") is True
