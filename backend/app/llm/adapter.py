"""LiteLLM to LangChain adapter — wraps LiteLLMClientImpl as BaseChatModel.

Used by both v2 (semantic_mapper) and v3 (build_react_agent) to make
our LiteLLM client compatible with LangChain/LangGraph's chat model interface.
"""

from __future__ import annotations

from typing import Any

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage, BaseMessage
from langchain_core.outputs import ChatResult, ChatGeneration


class LiteLLMChatAdapter(BaseChatModel):
    """Wraps LiteLLMClientImpl to satisfy LangChain BaseChatModel interface."""

    llm_client: Any
    _bound_tools: list | None = None

    def __init__(self, llm_client: Any, **kwargs: Any):
        super().__init__(llm_client=llm_client, **kwargs)

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        raise NotImplementedError("Use async version")

    async def _agenerate(
        self, messages: list[BaseMessage], stop=None, run_manager=None, **kwargs
    ) -> ChatResult:
        dict_msgs = []
        for m in messages:
            if hasattr(m, "type"):
                role = "assistant" if m.type == "ai" else ("system" if m.type == "system" else "user")
            else:
                role = "user"
            dict_msgs.append({"role": role, "content": str(m.content)})

        tools = kwargs.pop("tools", None) or self._bound_tools
        if tools:
            kwargs["tools"] = [
                t if isinstance(t, dict)
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

        content, _ = await self.llm_client.complete(dict_msgs, **kwargs)
        return ChatResult(generations=[ChatGeneration(message=AIMessage(content=content))])

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
