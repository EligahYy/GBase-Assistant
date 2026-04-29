"""用户查询模式 ORM 模型：学习用户高频查询习惯。"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class UserPattern(Base):
    __tablename__ = "user_patterns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    user_fingerprint: Mapped[str | None] = mapped_column(String(64), nullable=True)
    table_name: Mapped[str | None] = mapped_column(String(100), nullable=True)
    pattern_type: Mapped[str | None] = mapped_column(String(50), nullable=True)
    count: Mapped[int] = mapped_column(Integer, default=1)
    last_used: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
