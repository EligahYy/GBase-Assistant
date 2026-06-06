"""AG-UI 事件编码器。将 Agent 输出转为标准 SSE 事件。"""

from __future__ import annotations

import json
from enum import StrEnum


class EventType(StrEnum):
    TEXT_MESSAGE_CONTENT = "TEXT_MESSAGE_CONTENT"
    TOOL_CALL_START = "TOOL_CALL_START"
    TOOL_CALL_RESULT = "TOOL_CALL_RESULT"
    TOOL_CALL_END = "TOOL_CALL_END"
    STATE_DELTA = "STATE_DELTA"
    RUN_STARTED = "RUN_STARTED"
    RUN_FINISHED = "RUN_FINISHED"
    RUN_ERROR = "RUN_ERROR"
    # ── Thinking visibility ──
    THINKING_START = "THINKING_START"
    THINKING_CONTENT = "THINKING_CONTENT"
    THINKING_END = "THINKING_END"
    # ── Step lifecycle ──
    STEP_STARTED = "STEP_STARTED"
    STEP_FINISHED = "STEP_FINISHED"


class EventEncoder:
    """将 LangGraph Agent 输出编码为 AG-UI 标准 SSE 事件字符串。

    每个编码方法返回一个可直接写入 SSE 流的完整行：
        data: {"type":"...","key":"value",...}\n\n

    所有公共方法都是 @staticmethod，无需实例化。
    """

    @staticmethod
    def _encode(event_type: EventType, **kwargs: object) -> str:
        payload: dict[str, object] = {"type": event_type.value}
        payload.update(kwargs)
        return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"

    @staticmethod
    def run_started(conversation_id: str) -> str:
        return EventEncoder._encode(
            EventType.RUN_STARTED, conversation_id=conversation_id
        )

    @staticmethod
    def text_delta(content: str) -> str:
        return EventEncoder._encode(EventType.TEXT_MESSAGE_CONTENT, delta=content)

    @staticmethod
    def tool_call_start(tool_name: str, args: dict | None = None, agent_name: str = "") -> str:
        return EventEncoder._encode(
            EventType.TOOL_CALL_START, tool_name=tool_name, args=args or {}, agent_name=agent_name
        )

    @staticmethod
    def tool_call_end(tool_name: str, agent_name: str = "") -> str:
        return EventEncoder._encode(EventType.TOOL_CALL_END, tool_name=tool_name, agent_name=agent_name)

    @staticmethod
    def tool_call_result(tool_name: str, result: dict) -> str:
        return EventEncoder._encode(
            EventType.TOOL_CALL_RESULT, tool_name=tool_name, result=result
        )

    @staticmethod
    def state_delta(path: str, value: dict) -> str:
        return EventEncoder._encode(EventType.STATE_DELTA, path=path, value=value)

    @staticmethod
    def run_finished() -> str:
        return EventEncoder._encode(EventType.RUN_FINISHED)

    @staticmethod
    def run_error(message: str) -> str:
        return EventEncoder._encode(EventType.RUN_ERROR, message=message)

    @staticmethod
    def thinking_start() -> str:
        return EventEncoder._encode(EventType.THINKING_START)

    @staticmethod
    def thinking_delta(delta: str) -> str:
        return EventEncoder._encode(EventType.THINKING_CONTENT, delta=delta)

    @staticmethod
    def thinking_end() -> str:
        return EventEncoder._encode(EventType.THINKING_END)

    @staticmethod
    def step_started(agent_name: str, step_index: int = 0) -> str:
        return EventEncoder._encode(
            EventType.STEP_STARTED, agent_name=agent_name, step_index=step_index,
        )

    @staticmethod
    def step_finished(agent_name: str) -> str:
        return EventEncoder._encode(EventType.STEP_FINISHED, agent_name=agent_name)

    @staticmethod
    def chart_config(config: dict) -> str:
        """发送图表配置给前端。"""
        return EventEncoder._encode(
            EventType.STATE_DELTA, path="chart_config", value=config
        )

    @staticmethod
    def sql_event(sql: str) -> str:
        """发送生成的 SQL 给前端。"""
        return EventEncoder._encode(
            EventType.STATE_DELTA, path="sql", value={"sql": sql}
        )

    @staticmethod
    def result_event(result: dict) -> str:
        """发送查询结果给前端。"""
        return EventEncoder._encode(
            EventType.STATE_DELTA, path="result", value=result
        )
