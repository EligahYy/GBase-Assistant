from __future__ import annotations

import json
from datetime import datetime

from pydantic import BaseModel, field_validator


class ChatRequest(BaseModel):
    message: str
    conversation_id: str | None = None
    db_connection_id: str | None = None
    model: str | None = None  # 用户覆盖模型


class MessageResponse(BaseModel):
    id: str
    role: str
    content: str
    message_type: str | None
    sql_generated: str | None
    sql_validated: bool | None
    query_result: dict | None
    chart_config: dict | None
    token_usage: dict | None
    created_at: datetime

    model_config = {"from_attributes": True}

    @field_validator("token_usage", mode="before")
    @classmethod
    def parse_token_usage(cls, v: object) -> dict | None:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, ValueError):
                return None
        return v  # type: ignore[return-value]

    @field_validator("query_result", mode="before")
    @classmethod
    def parse_query_result(cls, v: object) -> dict | None:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, ValueError):
                return None
        return v  # type: ignore[return-value]

    @field_validator("chart_config", mode="before")
    @classmethod
    def parse_chart_config(cls, v: object) -> dict | None:
        if isinstance(v, str):
            try:
                return json.loads(v)
            except (json.JSONDecodeError, ValueError):
                return None
        return v  # type: ignore[return-value]

    @classmethod
    def from_orm_model(cls, obj) -> MessageResponse:
        return cls(
            id=obj.id,
            role=obj.role,
            content=obj.content,
            message_type=obj.message_type,
            sql_generated=obj.sql_generated,
            sql_validated=obj.sql_validated,
            query_result=obj.query_result,
            chart_config=obj.chart_config,
            token_usage=obj.get_token_usage(),
            created_at=obj.created_at,
        )


class ConversationResponse(BaseModel):
    id: str
    title: str | None
    db_connection_id: str | None
    model_used: str | None
    archived: bool = False
    tags: list[str] = []
    folder_id: str | None = None
    created_at: datetime
    messages: list[MessageResponse] = []

    model_config = {"from_attributes": True}


class ChatResponse(BaseModel):
    conversation_id: str
    message: MessageResponse


class FolderResponse(BaseModel):
    id: str
    name: str
    conversation_count: int = 0
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class BatchRequest(BaseModel):
    ids: list[str]
    action: str  # "archive" | "delete" | "move"
    folder_id: str | None = None
