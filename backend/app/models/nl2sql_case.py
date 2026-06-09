"""NL2SQL Case — stores validated query examples for learning and evaluation."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Integer, JSON, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class NL2SQLCase(Base):
    """A validated NL2SQL example — question + SQL pair with quality metadata."""

    __tablename__ = "nl2sql_cases"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    sql: Mapped[str] = mapped_column(Text, nullable=False)
    semantic_model_id: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    db_connection_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    schema_version: Mapped[str | None] = mapped_column(String(32), nullable=True)
    query_ir_json: Mapped[str | None] = mapped_column(Text, nullable=True)

    status: Mapped[str] = mapped_column(String(16), default="pending")  # pending | verified | rejected | deprecated
    quality_score: Mapped[float] = mapped_column(Float, default=0.0)
    usage_count: Mapped[int] = mapped_column(Integer, default=0)
    acceptance_rate: Mapped[float] = mapped_column(Float, default=0.0)

    source: Mapped[str] = mapped_column(String(16), default="auto")  # auto | manual | import
    conversation_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)

    reviewed_by: Mapped[str | None] = mapped_column(String(64), nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))


class NL2SQLAttempt(Base):
    """Records each NL2SQL execution attempt for debugging and analysis."""

    __tablename__ = "nl2sql_attempts"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    conversation_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    sql: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="pending")  # success | validation_failed | execution_failed | semantic_failed
    error_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    error_category: Mapped[str | None] = mapped_column(String(32), nullable=True)
    latency_ms: Mapped[float | None] = mapped_column(Float, nullable=True)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    query_ir_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
