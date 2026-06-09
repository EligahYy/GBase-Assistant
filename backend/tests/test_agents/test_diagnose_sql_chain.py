"""Diagnostic test: trace the full SQL chain for "查询25年全年销售额".

Properly mocks all DB-dependent tools to simulate a production environment.
Each tool returns realistic results matching the user's actual scenario.
"""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from langchain_core.messages import AIMessage, HumanMessage, ToolCall
from langchain_core.outputs import ChatGeneration, ChatResult

from app.agents.graph import _parse_tool_calls


# ═══════════════════════════════════════════════════════════════════════════════
# Mocks
# ═══════════════════════════════════════════════════════════════════════════════

class ScriptedLLM:
    """Returns predefined responses in sequence."""

    def __init__(self, responses: list[AIMessage]):
        self.responses = responses
        self.call_count = 0

    async def _agenerate(self, messages, **kwargs):
        idx = min(self.call_count, len(self.responses) - 1)
        resp = self.responses[idx]
        self.call_count += 1
        return ChatResult(generations=[ChatGeneration(message=resp)])


def _tc(name: str, args: dict) -> AIMessage:
    return AIMessage(content="", tool_calls=[ToolCall(name=name, args=args, id=f"call_{name}")])


def _fa(answer: str) -> AIMessage:
    return AIMessage(content="", tool_calls=[ToolCall(
        name="final_answer", args={"answer": answer, "sources": []}, id="call_fa"
    )])


def _multi_tc(*calls: tuple[str, dict]) -> AIMessage:
    return AIMessage(content="", tool_calls=[
        ToolCall(name=name, args=args, id=f"call_{name}")
        for name, args in calls
    ])


# ═══════════════════════════════════════════════════════════════════════════════
# Scenario: "查询25年全年销售额" — from user's actual UI trace
# ═══════════════════════════════════════════════════════════════════════════════

SCENARIO_QUERY = "查询25年全年销售额"

SCENARIO_RESPONSES = [
    # Step 1: Schema exploration
    _tc("search_schemas", {"query": "销售额 订单 2025"}),
    # Step 2: get table profiles
    _multi_tc(
        ("get_table_profile", {"table_name": "orders"}),
        ("get_table_profile", {"table_name": "order_items"}),
    ),
    # Step 3: Direct SQL exploration
    _tc("execute_sql", {"sql": "SHOW TABLES"}),
    # Step 4: DESCRIBE both tables
    _multi_tc(
        ("execute_sql", {"sql": "DESCRIBE orders"}),
        ("execute_sql", {"sql": "DESCRIBE order_items"}),
    ),
    # Step 5: Data exploration
    _multi_tc(
        ("execute_sql", {"sql": "SELECT DISTINCT status FROM orders WHERE order_date >= '2025-01-01'"}),
        ("execute_sql", {"sql": "SELECT MIN(order_date), MAX(order_date) FROM orders"}),
    ),
    # Step 6: Final query via submit_sql
    _tc("submit_sql", {"sql": "SELECT SUM(pay_amount) AS total_sales FROM orders WHERE order_date >= '2025-01-01' AND order_date < '2026-01-01' AND status IN ('paid','shipped','delivered')"}),
    # Step 7: After seeing result, call final_answer
    _fa("2025年全年销售额为 **856,000.00 元**。\n\n数据范围：2025-01-05 至 2025-06-10（上半年数据），订单状态包含 paid/shipped/delivered。"),
]


# ═══════════════════════════════════════════════════════════════════════════════
# Mock tool results — simulate production DB responses
# ═══════════════════════════════════════════════════════════════════════════════

class MockExecuteSQLTool:
    """Mock ExecuteSQLTool class that sql_execute node can instantiate."""
    def __init__(self, db_connection_id: str = ""):
        self._db_connection_id = db_connection_id
        self.name = "execute_sql"

    async def execute(self, sql: str = "", **kw):
        q = sql or kw.get("sql", "")
        qu = q.upper().replace("  ", " ")
        if "SHOW TABLES" in qu:
            return {"columns": ["Tables_in_test"], "rows": [["customers"], ["order_items"], ["orders"], ["products"], ["sales_regions"]], "row_count": 5, "execution_time_ms": 13.68, "truncated": False}
        if "DESCRIBE ORDERS" in qu:
            return {"columns": ["Field","Type"], "rows": [["order_id","int"],["pay_amount","decimal"],["order_date","datetime"],["status","varchar"]], "row_count": 4, "execution_time_ms": 20.68, "truncated": False}
        if "DESCRIBE ORDER_ITEMS" in qu:
            return {"columns": ["Field","Type"], "rows": [["item_id","int"],["subtotal","decimal"],["quantity","int"]], "row_count": 3, "execution_time_ms": 18.43, "truncated": False}
        if "DISTINCT STATUS" in qu:
            return {"columns": ["status"], "rows": [["pending"],["paid"],["shipped"],["delivered"]], "row_count": 4, "execution_time_ms": 127.79, "truncated": False}
        if "MIN(ORDER_DATE)" in qu:
            return {"columns": ["min_date","max_date"], "rows": [["2025-01-05","2025-06-10"]], "row_count": 1, "execution_time_ms": 91.01, "truncated": False}
        if "SUM(PAY_AMOUNT)" in qu or "SUM(pay_amount)" in q:
            return {"columns": ["total_sales"], "rows": [[856000.00]], "row_count": 1, "execution_time_ms": 45.30, "truncated": False}
        return {"columns": [], "rows": [], "row_count": 0, "execution_time_ms": 1.0, "truncated": False}

    def format_result(self, result):
        row_count = result.get("row_count", 0) if isinstance(result, dict) else 0
        return {"summary": f"查询完成: {row_count} 行", "detail": result, "truncated": False}

    def to_openai_schema(self):
        return {"type": "function", "function": {"name": "execute_sql", "description": "Execute a read-only SQL statement.", "parameters": {"type": "object", "properties": {"sql": {"type": "string", "description": "The SQL statement"}}, "required": ["sql"]}}}


# ═══════════════════════════════════════════════════════════════════════════════
# Build a realistic mock tool set
# ═══════════════════════════════════════════════════════════════════════════════

def _make_mock_schema_tool(name: str, description: str):
    """Create a minimal mock for schema tools (search_schemas, get_table_profile, find_join_path)."""
    mock = MagicMock()
    mock.name = name
    mock.execute = AsyncMock(return_value=[])
    mock.format_result = MagicMock(return_value={"summary": f"{name} result", "detail": None, "truncated": False})
    mock.to_openai_schema = lambda: {
        "type": "function", "function": {"name": name, "description": description,
        "parameters": {"type": "object", "properties": {}, "required": []}}
    }
    return mock


def _make_mock_tools():
    """Return a list of mocked tools that match what get_unified_agent_tools produces."""
    from app.agents.tools.sql_tools import SubmitSQLTool
    from app.agents.agents.unified_agent import FinalAnswerTool

    tools = [
        _make_mock_schema_tool("search_schemas", "Search database tables"),
        _make_mock_schema_tool("get_table_profile", "Get table column details"),
        _make_mock_schema_tool("find_join_path", "Find JOIN path between tables"),
        MockExecuteSQLTool(),
        SubmitSQLTool(),
        FinalAnswerTool(),
    ]
    return tools


# ═══════════════════════════════════════════════════════════════════════════════
# The diagnostic test
# ═══════════════════════════════════════════════════════════════════════════════

@pytest.mark.asyncio
async def test_diagnose_full_sql_chain(capsys):
    """Trace through the full "查询25年全年销售额" chain, printing every transition."""
    from app.agents.graph import build_graph

    print("\n" + "=" * 80)
    print("DIAGNOSTIC: 查询25年全年销售额 — Full Chain Trace")
    print("=" * 80)

    llm = ScriptedLLM(SCENARIO_RESPONSES)

    with (
        patch("app.agents.graph.LiteLLMChatAdapter", return_value=llm),
        patch("app.dependencies.get_llm_client", return_value=MagicMock()),
        patch("app.agents.graph.ExecuteSQLTool", new=MockExecuteSQLTool),
        patch("app.agents.graph.get_unified_agent_tools", return_value=_make_mock_tools()),
    ):
        graph = build_graph(db_connection_id="mock-db-1")

        initial_state = {
            "messages": [HumanMessage(content=SCENARIO_QUERY)],
            "db_connection_id": "mock-db-1",
            "agent_step": 0,
            "agent_finished": False,
            "sql": {},
            "knowledge": {},
        }

        print(f"\nInitial: agent_step=0, LLM responses={len(SCENARIO_RESPONSES)}\n")

        step_count = 0
        try:
            async for mode, events in graph.astream(
                initial_state,
                config={"configurable": {"thread_id": "diag-1"}},
                stream_mode=["custom", "updates"],
            ):
                if mode == "custom":
                    for ev in events:
                        if isinstance(ev, dict):
                            for key, val in ev.items():
                                if key == "thinking_delta":
                                    print(f"  💭 THINKING: {str(val)[:120]}")
                                elif key == "step_started":
                                    print(f"  ▶ STEP_STARTED: {val.get('agent_name')}")
                                elif key == "step_finished":
                                    print(f"  ◀ STEP_FINISHED: {val.get('agent_name')}")
                                elif key == "tool_call_start":
                                    step_count += 1
                                    tc_name = val.get("name", "")
                                    tc_args = val.get("args", {})
                                    args_str = json.dumps(tc_args, ensure_ascii=False)
                                    if len(args_str) > 150:
                                        args_str = args_str[:150] + "..."
                                    print(f"\n{'─'*60}")
                                    print(f"  🔧 #{step_count} {tc_name}({args_str})")
                                elif key == "tool_call_result":
                                    result = val.get("result", {})
                                    if isinstance(result, dict):
                                        summary = result.get("summary", "")
                                        status = result.get("status", "")
                                        detail = result.get("detail", {})
                                        if isinstance(detail, dict) and "sql" in detail:
                                            summary += f" [sql={detail['sql'][:80]}]"
                                        if status:
                                            summary += f" [status={status}]"
                                    else:
                                        summary = str(result)
                                    print(f"     ✓ {summary[:200]}")
                                elif key == "delta":
                                    delta = val if isinstance(val, str) else str(val.get("delta", ""))
                                    if len(delta) > 200:
                                        delta = delta[:200] + "...[truncated]"
                                    print(f"\n  📝 TEXT_DELTA: {delta}")
                                elif key == "state_delta":
                                    if isinstance(val, str):
                                        print(f"  📊 STATE_DELTA: {val[:150]}")
                                        continue
                                    path = val.get("path", "")
                                    value = val.get("value", {})
                                    if isinstance(value, dict):
                                        if path == "result":
                                            rows = value.get("rows", [])
                                            print(f"  📊 STATE_DELTA({path}): {len(rows)} rows, cols={value.get('columns', [])}")
                                        elif path == "sql":
                                            print(f"  📊 STATE_DELTA({path}): sql={str(value.get('sql', ''))[:100]}, valid={value.get('validation', {}).get('valid')}")
                                        else:
                                            print(f"  📊 STATE_DELTA({path})")
                                    else:
                                        print(f"  📊 STATE_DELTA({path}): {str(value)[:100]}")

                elif mode == "updates":
                    for node_name, node_output in events.items():
                        if node_name == "unified_agent":
                            step = node_output.get("agent_step", "?")
                            finished = node_output.get("agent_finished", False)
                            has_fa = bool(node_output.get("final_response"))
                            msgs = node_output.get("messages", [])
                            tc_info = ""
                            if msgs:
                                tcs, _ = _parse_tool_calls(msgs[-1]) if hasattr(msgs[-1], 'tool_calls') else (None, None)
                                if tcs:
                                    tc_info = f", tool_calls={[t['name'] for t in tcs]}"
                            print(f"\n  🤖 AGENT: step={step}, finished={finished}, final={has_fa}{tc_info}")
                        elif node_name == "unified_tools":
                            msgs = node_output.get("messages", [])
                            print(f"  🔨 TOOLS: {len(msgs)} msg(s)")
                        elif node_name == "sql_validate":
                            v = node_output.get("sql", {}).get("validation", {})
                            print(f"  🔍 VALIDATE: valid={v.get('valid')}, errors={v.get('errors')}")
                        elif node_name == "sql_execute":
                            sql_s = node_output.get("sql", {})
                            print(f"  ⚡ EXECUTE: phase={sql_s.get('phase')}, rows={sql_s.get('query_result', {}).get('row_count', 0)}, error={sql_s.get('execution_error')}")

        except Exception as e:
            import traceback
            print(f"\n  ❌ EXCEPTION: {type(e).__name__}: {e}")
            traceback.print_exc()

        # ── Final state ──
        final_state = await graph.aget_state({"configurable": {"thread_id": "diag-1"}})
        sv = final_state.values if final_state else {}

        print(f"\n{'='*80}")
        print("FINAL STATE")
        print(f"{'='*80}")
        print(f"  agent_step={sv.get('agent_step')}, agent_finished={sv.get('agent_finished')}")
        print(f"  final_response={repr(sv.get('final_response', ''))[:200]}")
        print(f"  sql.phase={sv.get('sql', {}).get('phase')}")
        print(f"  sql.retry_count={sv.get('sql', {}).get('retry_count')}")
        print(f"  LLM calls={llm.call_count}, tool_calls={step_count}")

        msgs = sv.get("messages", [])
        print(f"\n  Messages ({len(msgs)}):")
        for i, m in enumerate(msgs):
            role = type(m).__name__
            content = str(m.content)[:120] if hasattr(m, "content") and m.content else "(empty)"
            tcs = None
            if hasattr(m, "tool_calls") and m.tool_calls:
                tcs = [tc.get("name", "?") for tc in m.tool_calls]
            print(f"    [{i:2d}] {role}: {content}{' TC=' + str(tcs) if tcs else ''}")

        # ── Verdict ──
        print(f"\n{'='*80}")
        print("VERDICT")
        print(f"{'='*80}")

        issues = []

        # submit_sql called?
        sub_calls = [m for m in msgs if hasattr(m, "tool_calls") and m.tool_calls
                     and any(tc.get("name") == "submit_sql" for tc in m.tool_calls)]
        print(f"  submit_sql called: {'✅' if sub_calls else '❌'} ({len(sub_calls)}x)")

        # SQL executed?
        phase = sv.get("sql", {}).get("phase")
        if phase == "completed":
            print(f"  SQL execution: ✅ (completed, {sv['sql'].get('query_result', {}).get('row_count', 0)} rows)")
        elif phase == "execution_failed":
            issues.append(f"SQL execution failed: {sv['sql'].get('execution_error')}")
            print(f"  SQL execution: ❌ ({phase})")
        else:
            print(f"  SQL execution: ❓ ({phase})")

        # final_answer called?
        fa_msgs = [m for m in msgs if hasattr(m, "tool_calls") and m.tool_calls
                   and any(tc.get("name") == "final_answer" for tc in m.tool_calls)]
        has_fa = bool(fa_msgs)
        has_fr = bool(sv.get("final_response"))
        if has_fa:
            print(f"  final_answer: ✅ ({len(fa_msgs)}x)")
        elif has_fr:
            print(f"  final_answer: ⚠️ (text fallback, {len(sv['final_response'])} chars)")
        else:
            issues.append("No final_answer AND no final_response!")
            print(f"  final_answer: ❌")

        if issues:
            print(f"\n  ❌ ISSUES:")
            for i in issues:
                print(f"     - {i}")
            pytest.fail("\n".join(issues))
        else:
            print(f"\n  ✅ SQL chain completed successfully!")
