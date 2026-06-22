"""LiteLLM to LangChain adapter — wraps LiteLLMClientImpl as BaseChatModel.

Makes the project's LiteLLM client compatible with LangChain/LangGraph.
"""

from __future__ import annotations

import json
from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage, ToolMessage
from langchain_core.outputs import ChatGeneration, ChatResult


class LiteLLMChatAdapter(BaseChatModel):
    """Wraps LiteLLMClientImpl to satisfy LangChain BaseChatModel interface."""

    llm_client: Any
    _bound_tools: list | None = None

    def __init__(self, llm_client: Any, **kwargs: Any):
        super().__init__(llm_client=llm_client, **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError("Use async version")

    async def _agenerate(self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs) -> ChatResult:
        dict_msgs = []
        for m in messages:
            if isinstance(m, ToolMessage):
                dict_msgs.append(
                    {
                        "role": "tool",
                        "content": str(m.content),
                        "tool_call_id": m.tool_call_id,
                    }
                )
                continue

            role = "assistant" if m.type == "ai" else ("system" if m.type == "system" else "user")
            message: dict[str, Any] = {"role": role, "content": str(m.content)}
            if isinstance(m, AIMessage) and m.tool_calls:
                message["tool_calls"] = [
                    {
                        "id": tool_call.get("id", f"call_{index}"),
                        "type": "function",
                        "function": {
                            "name": tool_call["name"],
                            "arguments": json.dumps(tool_call.get("args", {}), ensure_ascii=False),
                        },
                    }
                    for index, tool_call in enumerate(m.tool_calls)
                ]
            dict_msgs.append(message)

        tools = kwargs.pop("tools", None) or self._bound_tools
        if tools:
            kwargs["tools"] = [
                t
                if isinstance(t, dict)
                else {
                    "type": "function",
                    "function": {
                        "name": t.name,
                        "description": t.description,
                        "parameters": t.args_schema.schema() if t.args_schema else {},
                    },
                }
                for t in tools
            ]

        content, _, tool_calls = await self.llm_client.complete(dict_msgs, **kwargs)

        # Build AIMessage with tool_calls if the model responded with function calls
        ai_message_kwargs: dict = {"content": content}
        if tool_calls:
            from langchain_core.messages import ToolCall

            lc_tool_calls = [
                ToolCall(
                    name=tc["name"],
                    args=tc["args"],
                    id=tc.get("id", f"call_{i}"),
                )
                for i, tc in enumerate(tool_calls)
            ]
            ai_message_kwargs["tool_calls"] = lc_tool_calls

        return ChatResult(generations=[ChatGeneration(message=AIMessage(**ai_message_kwargs))])

    def bind_tools(self, tools: list, **kwargs):
        clone = LiteLLMChatAdapter(self.llm_client)
        clone._bound_tools = tools
        return clone

    @property
    def _llm_type(self) -> str:
        return "litellm-adapter"

    @property
    def _identifying_params(self):
        return {}
