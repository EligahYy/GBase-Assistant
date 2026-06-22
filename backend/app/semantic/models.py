"""Semantic layer ORM models — business data models, metrics, dimensions, members, joins."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


def _uid() -> str:
    return uuid.uuid4().hex[:12]


class SemanticModel(Base):
    """A business data model — a scoped set of tables available for NL2SQL querying."""

    __tablename__ = "semantic_models"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    db_connection_id: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    description: Mapped[str] = mapped_column(Text, default="")
    table_names: Mapped[list[str]] = mapped_column(JSON, default=list)
    primary_table: Mapped[str | None] = mapped_column(String(64), nullable=True)
    enabled_for_nl2sql: Mapped[bool] = mapped_column(Boolean, default=True)
    schema_version: Mapped[str] = mapped_column(String(32), default="")
    prompt_hint: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=lambda: datetime.now(UTC))
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, default=lambda: datetime.now(UTC), onupdate=lambda: datetime.now(UTC)
    )

    metrics: Mapped[list[SemanticMetric]] = relationship(back_populates="model", cascade="all, delete-orphan")
    dimensions: Mapped[list[SemanticDimension]] = relationship(back_populates="model", cascade="all, delete-orphan")
    joins: Mapped[list[SemanticJoin]] = relationship(back_populates="model", cascade="all, delete-orphan")


class SemanticMetric(Base):
    """A business metric definition — e.g., 销售额 = SUM(orders.pay_amount)."""

    __tablename__ = "semantic_metrics"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    semantic_model_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("semantic_models.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    synonyms: Mapped[list[str]] = mapped_column(JSON, default=list)
    expression: Mapped[str] = mapped_column(Text, nullable=False)
    source_tables: Mapped[list[str]] = mapped_column(JSON, default=list)
    default_filters: Mapped[list[dict]] = mapped_column(JSON, default=list)
    allowed_dimensions: Mapped[list[str]] = mapped_column(JSON, default=list)
    description: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(16), default="draft")  # draft | verified | deprecated

    model: Mapped[SemanticModel] = relationship(back_populates="metrics")


class SemanticDimension(Base):
    """A business dimension — e.g., 区域 = sales_regions.region_name."""

    __tablename__ = "semantic_dimensions"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    semantic_model_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("semantic_models.id"), nullable=False, index=True
    )
    name: Mapped[str] = mapped_column(String(128), nullable=False)
    column_ref: Mapped[str] = mapped_column(String(256), nullable=False)
    synonyms: Mapped[list[str]] = mapped_column(JSON, default=list)
    data_type: Mapped[str] = mapped_column(String(32), default="string")
    time_granularities: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    hierarchy: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")

    model: Mapped[SemanticModel] = relationship(back_populates="dimensions")


class SemanticMember(Base):
    """Member values for a dimension — e.g., "已完成" ↔ "delivered"."""

    __tablename__ = "semantic_members"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    dimension_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("semantic_dimensions.id"), nullable=False, index=True
    )
    raw_value: Mapped[str] = mapped_column(String(256), nullable=False)
    display_value: Mapped[str] = mapped_column(String(256), nullable=False)
    aliases: Mapped[list[str]] = mapped_column(JSON, default=list)
    frequency: Mapped[int | None] = mapped_column(Integer, nullable=True)
    status: Mapped[str] = mapped_column(String(16), default="draft")


class SemanticJoin(Base):
    """Governed JOIN relationship between two tables in a model."""

    __tablename__ = "semantic_joins"

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=_uid)
    semantic_model_id: Mapped[str] = mapped_column(
        String(32), ForeignKey("semantic_models.id"), nullable=False, index=True
    )
    left_table: Mapped[str] = mapped_column(String(64), nullable=False)
    right_table: Mapped[str] = mapped_column(String(64), nullable=False)
    condition: Mapped[str] = mapped_column(Text, nullable=False)
    cardinality: Mapped[str] = mapped_column(String(16), default="many_to_one")
    source: Mapped[str] = mapped_column(String(16), default="manual")  # ddl_fk | inferred | manual
    confidence: Mapped[float] = mapped_column(Float, default=0.0)
    status: Mapped[str] = mapped_column(String(16), default="candidate")  # candidate | verified | rejected

    model: Mapped[SemanticModel] = relationship(back_populates="joins")
