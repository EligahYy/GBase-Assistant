"""Tests for new AG-UI event types (THINKING, STEP)."""

from __future__ import annotations

import json

from app.gateway.ag_ui_encoder import EventEncoder, EventType


class TestNewEventTypes:
    def test_thinking_start(self):
        sse = EventEncoder.thinking_start()
        data = json.loads(sse.split("data: ")[1].strip())
        assert data["type"] == "THINKING_START"

    def test_thinking_delta(self):
        sse = EventEncoder.thinking_delta("我需要检索表结构...")
        data = json.loads(sse.split("data: ")[1].strip())
        assert data["type"] == "THINKING_CONTENT"
        assert data["delta"] == "我需要检索表结构..."

    def test_thinking_end(self):
        sse = EventEncoder.thinking_end()
        data = json.loads(sse.split("data: ")[1].strip())
        assert data["type"] == "THINKING_END"

    def test_step_started(self):
        sse = EventEncoder.step_started("sql_agent", step_index=0)
        data = json.loads(sse.split("data: ")[1].strip())
        assert data["type"] == "STEP_STARTED"
        assert data["agent_name"] == "sql_agent"
        assert data["step_index"] == 0

    def test_step_finished(self):
        sse = EventEncoder.step_finished("sql_agent")
        data = json.loads(sse.split("data: ")[1].strip())
        assert data["type"] == "STEP_FINISHED"
        assert data["agent_name"] == "sql_agent"

    def test_existing_tool_events_still_work(self):
        sse = EventEncoder.tool_call_start("search_schemas", {"query": "sales"})
        data = json.loads(sse.split("data: ")[1].strip())
        assert data["type"] == "TOOL_CALL_START"
        assert data["tool_name"] == "search_schemas"
        assert data["args"] == {"query": "sales"}
