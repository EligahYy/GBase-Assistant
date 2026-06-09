"""v3.4 FinalAnswerTool — the only termination signal."""

from __future__ import annotations

from typing import Any

from app.agents.tools.base import ToolParameter


class FinalAnswerTool:
    """Signal that the agent is ready to respond."""

    @property
    def name(self) -> str:
        return "final_answer"

    @property
    def description(self) -> str:
        return "Submit your final answer to the user. Call this when you are ready to respond."

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(name="answer", type="string", description="Your final answer, in Chinese, with markdown"),
            ToolParameter(name="sources", type="array", description="List of sources used", required=False),
        ]

    async def execute(self, answer: str = "", sources: list[str] | None = None, **kwargs: Any) -> dict:
        return {"answer": answer or kwargs.get("answer", ""), "sources": sources or kwargs.get("sources", [])}

    def format_result(self, result: dict) -> dict:
        return {"summary": result.get("answer", "")[:100], "detail": result, "truncated": False}

    def to_openai_schema(self) -> dict:
        return {
            "type": "function", "function": {
                "name": self.name, "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "answer": {"type": "string", "description": "Your final answer to the user"},
                        "sources": {"type": "array", "items": {"type": "string"}, "description": "List of sources used"},
                    },
                    "required": ["answer"],
                },
            },
        }
