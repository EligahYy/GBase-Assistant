"""SQL feedback ORM model."""
from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class SQLFeedback(Base):
    __tablename__ = "sql_feedback"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    message_id: Mapped[str] = mapped_column(String(36), ForeignKey("messages.id"), nullable=False)
    action: Mapped[str] = mapped_column(String(20), nullable=False)  # accepted | rejected | modified
    original_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    modified_sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    feedback_note: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
