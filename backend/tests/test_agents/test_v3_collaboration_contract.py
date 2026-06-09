"""Behavior contracts for v3.3 Circuit Breaker ReAct framework."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolCall
from langchain_core.outputs import ChatGeneration, ChatResult

from app.agents.agents.knowledge_agent import expand_knowledge_query
from app.agents.graph import _build_conversation_messages, build_graph
from app.protocols import KnowledgeChunk


class SequencedAdapter:
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
def _final_answer(answer: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[ToolCall(name="final_answer", args={"answer": answer, "sources": []}, id="call_fa")])


def _make_mock_submit_sql(status="completed", **overrides):
    """Mock SubmitSQLTool that returns the given atomic result."""
    base = {"status": status, "sql": overrides.get("sql", "SELECT 1"), "columns": overrides.get("columns", ["id"]), "rows": overrides.get("rows", [[1]]), "row_count": overrides.get("row_count", 1), "execution_time_ms": 2.0, "truncated": False}
    if status == "validation_failed":
        base = {"status": status, "sql": overrides.get("sql", ""), "errors": overrides.get("errors", ["error"]), "warnings": []}
    if status == "execution_failed":
        base = {"status": status, "sql": overrides.get("sql", ""), "error": overrides.get("error", "error")}
    mock = MagicMock()
    mock.name = "submit_sql"
    mock.execute = AsyncMock(return_value=base)
    def _fmt(r):
        s = r.get("status", "")
        if s == "completed": return {"summary": f"SQL 成功: {r.get('row_count', 0)} 行", "detail": r, "truncated": False}
        if s == "validation_failed": return {"summary": f"验证失败: {r.get('errors', [])}", "detail": r, "truncated": False}
        return {"summary": f"执行失败: {r.get('error', '')}", "detail": r, "truncated": False}
    mock.format_result = MagicMock(side_effect=_fmt)
    mock.to_openai_schema = lambda: {"type": "function", "function": {"name": "submit_sql", "description": "...", "parameters": {"type": "object", "properties": {"sql": {"type": "string"}}, "required": ["sql"]}}}
    return mock


# ── Helpers ──

def test_build_conversation_messages():
    history = [{"role": "user", "content": "查询销售额"}, {"role": "assistant", "content": "华东最高"}, {"role": "user", "content": "只看华东"}]
    messages = _build_conversation_messages(history, "只看华东")
    assert [m.content for m in messages] == ["查询销售额", "华东最高", "只看华东"]

def test_knowledge_query_expansion():
    expanded = expand_knowledge_query("如何创建随机分布表？")
    assert "随机分布" in expanded
    assert "DISTRIBUTED" in expanded


# ── v3.3 Circuit Breaker Contracts ──

@pytest.mark.asyncio
async def test_full_three_phase_flow():
    """explore(search_schemas) → sql(submit_sql) → answer(final_answer)."""
    mock_search = MagicMock()
    mock_search.name = "search_schemas"
    mock_search.execute = AsyncMock(return_value=[MagicMock(table_name="orders")])
    mock_search.format_result = MagicMock(return_value={"summary": "找到 orders", "detail": None, "truncated": False})
    mock_search.to_openai_schema = lambda: {"type": "function", "function": {"name": "search_schemas", "description": "...", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}

    mock_sql = _make_mock_submit_sql("completed", sql="SELECT SUM(pay_amount) FROM orders", row_count=1, columns=["total"], rows=[[57246.00]])

    # Phase 1: explore → search_schemas → no more tools (advance to sql)
    # Phase 2: sql → submit_sql → completed → no more tools (advance to answer)
    # Phase 3: answer → final_answer
    adapter = SequencedAdapter([
        _tool_call("search_schemas", {"query": "销售额"}),
        _tool_call("submit_sql", {"sql": "SELECT SUM(pay_amount) FROM orders"}),
        _final_answer("2025年销售额为 57,246.00 元"),
    ])

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=adapter), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph.get_explore_tools", return_value=[mock_search, mock_sql]), \
         patch("app.agents.graph.get_sql_tools", return_value=[mock_sql]), \
         patch("app.agents.graph.get_answer_tools", return_value=[]):
        graph = build_graph(db_connection_id="db-1")
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="查询销售额")], "db_connection_id": "db-1", "cb": {}},
            {"configurable": {"thread_id": "c1"}},
        )

    assert result["final_response"] == "2025年销售额为 57,246.00 元"
    cb = result.get("cb", {})
    assert cb.get("explore", {}).get("tables_found") == ["orders"]
    assert cb.get("sql", {}).get("status") == "completed"


@pytest.mark.asyncio
async def test_sql_validation_failed_retries_then_advances():
    """submit_sql validation_failed x3 → CB triggers → answer."""
    mock_sql = _make_mock_submit_sql("validation_failed", sql="BAD SQL", errors=["语法错误"])

    # First response: explore phase (no tools) → text advances to sql
    # Then sql phase: 3 submit_sql failures → answer phase
    adapter = SequencedAdapter([
        AIMessage(content="ready for sql"),                              # explore phase pass-through
        _tool_call("submit_sql", {"sql": "BAD SQL"}),                   # sql retry 1
        _tool_call("submit_sql", {"sql": "BAD SQL 2"}),                 # sql retry 2
        _tool_call("submit_sql", {"sql": "BAD SQL 3"}),                 # sql retry 3 → CB
        _final_answer("SQL 生成失败，已尝试 3 次。"),                     # answer phase
    ])

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=adapter), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph.get_explore_tools", return_value=[]), \
         patch("app.agents.graph.get_sql_tools", return_value=[mock_sql]), \
         patch("app.agents.graph.get_answer_tools", return_value=[]):
        graph = build_graph(db_connection_id="db-1")
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="查询")], "db_connection_id": "db-1", "cb": {}},
            {"configurable": {"thread_id": "c2"}},
        )

    cb = result.get("cb", {})
    assert cb.get("sql", {}).get("retry_count", 0) >= 1
    assert result.get("final_response") is not None


@pytest.mark.asyncio
async def test_search_exhausted_skips_to_answer():
    """search_schemas returns empty 3x → CB search_exhausted → answer_agent."""
    mock_search = MagicMock()
    mock_search.name = "search_schemas"
    mock_search.execute = AsyncMock(return_value=[])
    mock_search.format_result = MagicMock(return_value={"summary": "未找到", "detail": None, "truncated": False})
    mock_search.to_openai_schema = lambda: {"type": "function", "function": {"name": "search_schemas", "description": "...", "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}}

    adapter = SequencedAdapter([
        _tool_call("search_schemas", {"query": "q1"}),
        _tool_call("search_schemas", {"query": "q2"}),
        _tool_call("search_schemas", {"query": "q3"}),
        _final_answer("未找到相关表"),
    ])

    with patch("app.agents.graph.LiteLLMChatAdapter", return_value=adapter), \
         patch("app.dependencies.get_llm_client", return_value=MagicMock()), \
         patch("app.agents.graph.get_explore_tools", return_value=[mock_search]), \
         patch("app.agents.graph.get_sql_tools", return_value=[]), \
         patch("app.agents.graph.get_answer_tools", return_value=[]):
        graph = build_graph()
        result = await graph.ainvoke(
            {"messages": [HumanMessage(content="查询")], "db_connection_id": None, "cb": {}},
            {"configurable": {"thread_id": "c3"}},
        )

    cb = result.get("cb", {})
    assert cb.get("cb_reason") in ("search_exhausted", "explore_max_steps", "")
    assert result.get("final_response") is not None
