"""Delegate tools — Supervisor tools that invoke specialist sub-agents."""

from __future__ import annotations

from app.agents.tools.base import AgentTool, ToolParameter


class DelegateToSQLAgent:
    """Delegate a data query request to the SQL Agent subgraph."""

    @property
    def name(self) -> str:
        return "delegate_to_sql_specialist"

    @property
    def description(self) -> str:
        return (
            "Delegate a data query request to the SQL specialist agent. "
            "The SQL agent will autonomously: explore the database schema, "
            "generate GBase 8a SQL, validate it, execute it, and return results. "
            "Use for: data queries, statistics, reports, chart data, monitoring queries."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="The user's natural language query (pass the original user message)",
            ),
        ]

    async def execute(self, query: str = "", **kwargs) -> dict:
        q = query or kwargs.get("query", "")
        return {"status": "delegated", "query": q}

    def format_result(self, result: dict) -> dict:
        return {"summary": f"委托 SQL Agent 处理: {result.get('query', '')[:50]}...", "detail": result, "truncated": False}

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The user's natural language data query"},
                    },
                    "required": ["query"],
                },
            },
        }


class DelegateToKnowledgeAgent:
    """Delegate a knowledge question to the Knowledge Agent subgraph."""

    @property
    def name(self) -> str:
        return "delegate_to_knowledge_specialist"

    @property
    def description(self) -> str:
        return (
            "Delegate a GBase 8a technical question to the Knowledge specialist agent. "
            "The Knowledge agent will search the product documentation and answer "
            "technical questions about GBase 8a features, syntax, configuration, errors. "
            "Use for: 'how to' questions, error codes, syntax reference, configuration."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="The user's technical question",
            ),
        ]

    async def execute(self, query: str = "", **kwargs) -> dict:
        q = query or kwargs.get("query", "")
        return {"status": "delegated", "query": q}

    def format_result(self, result: dict) -> dict:
        return {"summary": f"委托 Knowledge Agent 处理: {result.get('query', '')[:50]}...", "detail": result, "truncated": False}

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The user's technical question"},
                    },
                    "required": ["query"],
                },
            },
        }


class RespondGeneralTool:
    """Direct text response for casual conversation."""

    @property
    def name(self) -> str:
        return "respond_general"

    @property
    def description(self) -> str:
        return (
            "Send a direct conversational response to the user. "
            "Use for: greetings, casual chat, topics outside GBase 8a scope, "
            "or when the user needs guidance on what they can ask."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="message",
                type="string",
                description="The message to send to the user (in Chinese)",
            ),
        ]

    async def execute(self, message: str = "", **kwargs) -> str:
        return message or kwargs.get("message", "")

    def format_result(self, result: str) -> dict:
        return {"summary": result, "detail": None, "truncated": False}

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "message": {"type": "string", "description": "Response message to send to user"},
                    },
                    "required": ["message"],
                },
            },
        }


class AskUserClarificationTool:
    """Ask the user for clarification when intent is unclear."""

    @property
    def name(self) -> str:
        return "ask_user_clarification"

    @property
    def description(self) -> str:
        return (
            "Ask the user for clarification when their request is ambiguous. "
            "Use when: the intent is unclear, multiple interpretations are possible, "
            "or required information is missing (e.g., no database selected)."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="question",
                type="string",
                description="The clarification question to ask the user",
            ),
        ]

    async def execute(self, question: str = "", **kwargs) -> str:
        return question or kwargs.get("question", "")

    def format_result(self, result: str) -> dict:
        return {"summary": result, "detail": None, "truncated": False}

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "question": {"type": "string", "description": "Clarification question to ask"},
                    },
                    "required": ["question"],
                },
            },
        }


class DelegateToGeneralAgent:
    """Delegate general/ambiguous queries to the General Agent. Used by Supervisor for
    greetings, casual chat, unclear intent — anything that doesn't need SQL or Knowledge."""

    @property
    def name(self) -> str:
        return "delegate_to_general"

    @property
    def description(self) -> str:
        return (
            "Delegate to the General agent for greetings, casual chat, unclear intent, "
            "or any request that doesn't need SQL generation or knowledge base search."
        )

    @property
    def parameters(self) -> list[ToolParameter]:
        return [
            ToolParameter(
                name="query",
                type="string",
                description="The user's message to respond to",
            ),
        ]

    async def execute(self, query: str = "", **kwargs) -> dict:
        q = query or kwargs.get("query", "")
        return {"status": "delegated", "query": q}

    def format_result(self, result: dict) -> dict:
        return {"summary": "委托 General Agent 处理", "detail": result, "truncated": False}

    def to_openai_schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": {
                    "type": "object",
                    "properties": {
                        "query": {"type": "string", "description": "The user's message"},
                    },
                    "required": ["query"],
                },
            },
        }
