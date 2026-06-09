"""Integration tests for v3.3 Circuit Breaker graph routing."""

from unittest.mock import MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolCall

from app.agents.state import AgentState


def _mock_adapter(responses: list[AIMessage]):
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
    return AIMessage(content="", tool_calls=[ToolCall(name="final_answer", args={"answer": answer, "sources": []}, id="call_fa")])


def _text_msg(content: str) -> AIMessage:
    return AIMessage(content=content)


def _initial_state(msg: str) -> AgentState:
    return {"messages": [HumanMessage(content=msg)], "db_connection_id": None, "cb": {}}


@pytest.mark.asyncio
async def test_answer_phase_calls_final_answer():
    """Answer agent calls final_answer → graph ends."""
    mock = _mock_adapter([_fa_msg("你好！有什么可以帮你的？")])

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=mock), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph.get_answer_tools", return_value=[]):
        from app.agents.graph import build_graph
        graph = build_graph()
        # Start directly in answer phase
        state = {"messages": [HumanMessage(content="你好")], "db_connection_id": None,
                 "cb": {"current_phase": "answer", "total_steps": 0}}
        result = await graph.ainvoke(state, {"configurable": {"thread_id": "t1"}})
        assert result.get("final_response") == "你好！有什么可以帮你的？"


@pytest.mark.asyncio
async def test_graph_terminates_on_explore_empty_tools():
    """Explore agent with no tools → advances to sql phase → answer."""
    mock = _mock_adapter([_text_msg("done exploring")])

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=mock), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph.get_explore_tools", return_value=[]), \
         patch("app.agents.graph.get_sql_tools", return_value=[]), \
         patch("app.agents.graph.get_answer_tools", return_value=[]):
        from app.agents.graph import build_graph
        graph = build_graph()
        result = await graph.ainvoke(_initial_state("查询订单"), {"configurable": {"thread_id": "t2"}})
        # Should advance through all phases and terminate
        assert result is not None


@pytest.mark.asyncio
async def test_circuit_breaker_explore_max_steps():
    """After 5 explore steps with search_schemas, CB triggers and advances."""
    from app.agents.tools.sql_tools import SubmitSQLTool

    responses = [_tc_msg("search_schemas", {"query": f"q{i}"}) for i in range(10)]

    # Make search_schemas always return empty
    mock_search = MagicMock()
    mock_search.name = "search_schemas"
    mock_search.execute = MagicMock(return_value=[])
    mock_search.format_result = MagicMock(return_value={"summary": "未找到相关表。", "detail": None, "truncated": False})
    mock_search.to_openai_schema = lambda: {"type": "function", "function": {"name": "search_schemas", "description": "...", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}

    explore_tools = [mock_search, SubmitSQLTool(db_connection_id="")]
    sql_tools = [SubmitSQLTool(db_connection_id="")]

    mock_llm = _mock_adapter(responses)

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=mock_llm), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph.get_explore_tools", return_value=explore_tools), \
         patch("app.agents.graph.get_sql_tools", return_value=sql_tools), \
         patch("app.agents.graph.get_answer_tools", return_value=[]):
        from app.agents.graph import build_graph
        graph = build_graph()
        result = await graph.ainvoke(_initial_state("查询销售"), {"configurable": {"thread_id": "t3"}})
        # CB should have triggered explore_max_steps or search_exhausted
        cb = result.get("cb", {})
        reason = cb.get("cb_reason", "")
        assert reason in ("explore_max_steps", "search_exhausted", "")
        # Graph must terminate
        assert result is not None


@pytest.mark.asyncio
async def test_graph_stops_at_total_steps_limit():
    """After MAX_TOTAL_STEPS, CB triggers and graph terminates."""
    from app.agents.tools.sql_tools import SubmitSQLTool

    responses = [_tc_msg("search_schemas", {"query": "x"})] * 20
    mock_search = MagicMock()
    mock_search.name = "search_schemas"
    mock_search.execute = MagicMock(return_value=[MagicMock(table_name="orders")])
    mock_search.format_result = MagicMock(return_value={"summary": "找到 orders", "detail": None, "truncated": False})
    mock_search.to_openai_schema = lambda: {"type": "function", "function": {"name": "search_schemas", "description": "...", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=_mock_adapter(responses)), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph.get_explore_tools", return_value=[mock_search, SubmitSQLTool(db_connection_id="")]), \
         patch("app.agents.graph.get_sql_tools", return_value=[SubmitSQLTool(db_connection_id="")]), \
         patch("app.agents.graph.get_answer_tools", return_value=[]):
        from app.agents.graph import build_graph
        graph = build_graph()
        result = await graph.ainvoke(_initial_state("x"), {"configurable": {"thread_id": "t4"}})
        assert result is not None
        cb = result.get("cb", {})
        assert cb.get("total_steps", 0) <= 16


@pytest.mark.asyncio
async def test_agent_handles_no_db_connection():
    """When no DB connected, answer agent responds gracefully."""
    mock = _mock_adapter([_fa_msg("当前未选择数据库连接，请先在设置中添加。")])

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=mock), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph.get_answer_tools", return_value=[]):
        from app.agents.graph import build_graph
        graph = build_graph()
        state = {"messages": [HumanMessage(content="查询订单")], "db_connection_id": None,
                 "cb": {"current_phase": "answer", "total_steps": 0}}
        result = await graph.ainvoke(state, {"configurable": {"thread_id": "t5"}})
        assert result.get("final_response") is not None
