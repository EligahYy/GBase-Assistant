"""Message ORM 模型。token_usage 用 Text 存 JSON（兼容 SQLite）。"""
from __future__ import annotations

import json
import uuid
from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Message(Base):
    __tablename__ = "messages"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    conversation_id: Mapped[str] = mapped_column(
        String(36), ForeignKey("conversations.id", ondelete="CASCADE"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(20), nullable=False)  # "user" | "assistant"
    content: Mapped[str] = mapped_column(Text, nullable=False)
    message_type: Mapped[str | None] = mapped_column(String(20), nullable=True)  # "sql" | "qa" | "general"
    sql_generated: Mapped[str | None] = mapped_column(Text, nullable=True)
    sql_validated: Mapped[bool | None] = mapped_column(Boolean, nullable=True)
    token_usage: Mapped[str | None] = mapped_column(Text, nullable=True)  # JSON string
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    conversation: Mapped["Conversation"] = relationship("Conversation", back_populates="messages")  # noqa: F821

    def set_token_usage(self, usage: dict | None) -> None:
        self.token_usage = json.dumps(usage, ensure_ascii=False) if usage else None

    def get_token_usage(self) -> dict | None:
        return json.loads(self.token_usage) if self.token_usage else None
