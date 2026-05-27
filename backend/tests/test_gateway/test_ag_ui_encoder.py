"""EventEncoder 单元测试。"""

import json

from app.gateway.ag_ui_encoder import EventEncoder


class TestEventEncoder:
    def test_run_started(self):
        result = EventEncoder.run_started("conv-1")
        assert result.startswith("data: ")
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "RUN_STARTED"
        assert payload["conversation_id"] == "conv-1"

    def test_text_delta(self):
        result = EventEncoder.text_delta("Hello")
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "TEXT_MESSAGE_CONTENT"
        assert payload["delta"] == "Hello"

    def test_tool_call_start(self):
        result = EventEncoder.tool_call_start("schema_grounding", {"query": "test"})
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "TOOL_CALL_START"
        assert payload["tool_name"] == "schema_grounding"
        assert payload["args"] == {"query": "test"}

    def test_tool_call_start_default_args(self):
        """未传 args 时应为 {}。"""
        result = EventEncoder.tool_call_start("sql_generator")
        payload = json.loads(result[6:].strip())
        assert payload["args"] == {}

    def test_tool_call_end(self):
        result = EventEncoder.tool_call_end("sql_generator")
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "TOOL_CALL_END"
        assert payload["tool_name"] == "sql_generator"

    def test_tool_call_result(self):
        result = EventEncoder.tool_call_result("sql_executor", {"rows": 5, "time_ms": 120})
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "TOOL_CALL_RESULT"
        assert payload["result"]["rows"] == 5

    def test_state_delta(self):
        result = EventEncoder.state_delta("/grounding", {"tables": ["orders"]})
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "STATE_DELTA"
        assert payload["path"] == "/grounding"
        assert payload["value"]["tables"] == ["orders"]

    def test_run_finished(self):
        result = EventEncoder.run_finished()
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "RUN_FINISHED"

    def test_run_error(self):
        result = EventEncoder.run_error("Something went wrong")
        payload = json.loads(result[6:].strip())
        assert payload["type"] == "RUN_ERROR"
        assert payload["message"] == "Something went wrong"

    def test_sse_format(self):
        """所有事件必须符合 SSE 标准：data: {json}\n\n"""
        result = EventEncoder.text_delta("x")
        assert result.endswith("\n\n")
        assert result.count("\n") == 2

    def test_json_escape(self):
        """特殊字符应在 JSON 中正确转义。"""
        result = EventEncoder.text_delta('line1\nline2\t"quoted"')
        payload = json.loads(result[6:].strip())
        assert payload["delta"] == 'line1\nline2\t"quoted"'

    def test_all_events_end_with_double_newline(self):
        """所有事件类型都必须以 \n\n 结尾。"""
        events = [
            EventEncoder.run_started("c1"),
            EventEncoder.text_delta("x"),
            EventEncoder.tool_call_start("t"),
            EventEncoder.tool_call_end("t"),
            EventEncoder.tool_call_result("t", {}),
            EventEncoder.state_delta("/p", {}),
            EventEncoder.run_finished(),
            EventEncoder.run_error("e"),
        ]
        for event in events:
            assert event.endswith("\n\n"), f"Event {event[:50]} does not end with \\n\\n"
