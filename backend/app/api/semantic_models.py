"""Semantic model management API — CRUD for models, metrics, dimensions, joins."""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.semantic.models import (
    SemanticDimension,
    SemanticJoin,
    SemanticMember,
    SemanticMetric,
    SemanticModel,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/semantic-models", tags=["semantic-models"])


# ═══════════════════════════════════════════════════════════════════════════════
# Schemas
# ═══════════════════════════════════════════════════════════════════════════════

class SemanticModelCreate(BaseModel):
    name: str
    description: str = ""
    db_connection_id: str
    table_names: list[str] = Field(default_factory=list)
    primary_table: str | None = None
    prompt_hint: str | None = None

class SemanticModelUpdate(BaseModel):
    name: str | None = None
    description: str | None = None
    table_names: list[str] | None = None
    primary_table: str | None = None
    enabled_for_nl2sql: bool | None = None
    prompt_hint: str | None = None

class SemanticModelOut(BaseModel):
    id: str
    name: str
    description: str
    db_connection_id: str
    table_names: list[str]
    primary_table: str | None
    enabled_for_nl2sql: bool
    schema_version: str
    prompt_hint: str | None
    created_at: str
    updated_at: str

    class Config:
        from_attributes = True

class MetricCreate(BaseModel):
    name: str
    synonyms: list[str] = Field(default_factory=list)
    expression: str
    source_tables: list[str] = Field(default_factory=list)
    default_filters: list[dict] = Field(default_factory=list)
    allowed_dimensions: list[str] = Field(default_factory=list)
    description: str = ""
    status: str = "draft"

class MetricUpdate(BaseModel):
    name: str | None = None
    synonyms: list[str] | None = None
    expression: str | None = None
    source_tables: list[str] | None = None
    default_filters: list[dict] | None = None
    allowed_dimensions: list[str] | None = None
    description: str | None = None
    status: str | None = None

class DimensionCreate(BaseModel):
    name: str
    column_ref: str
    synonyms: list[str] = Field(default_factory=list)
    data_type: str = "string"
    time_granularities: list[str] | None = None
    hierarchy: list[str] | None = None
    status: str = "draft"

class JoinCreate(BaseModel):
    left_table: str
    right_table: str
    condition: str
    cardinality: str = "many_to_one"
    source: str = "manual"
    confidence: float = 0.0
    status: str = "candidate"

class JoinUpdate(BaseModel):
    condition: str | None = None
    cardinality: str | None = None
    confidence: float | None = None
    status: str | None = None


# ═══════════════════════════════════════════════════════════════════════════════
# Models CRUD
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("", response_model=list[SemanticModelOut])
async def list_models(db_connection_id: str | None = None, db: AsyncSession = Depends(get_db)):
    stmt = select(SemanticModel)
    if db_connection_id:
        stmt = stmt.where(SemanticModel.db_connection_id == db_connection_id)
    result = await db.execute(stmt)
    return result.scalars().all()


@router.post("", response_model=SemanticModelOut)
async def create_model(data: SemanticModelCreate, db: AsyncSession = Depends(get_db)):
    model = SemanticModel(**data.model_dump())
    db.add(model)
    await db.commit()
    await db.refresh(model)
    return model


@router.get("/{model_id}", response_model=SemanticModelOut)
async def get_model(model_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SemanticModel).where(SemanticModel.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Semantic model not found")
    return model


@router.patch("/{model_id}", response_model=SemanticModelOut)
async def update_model(model_id: str, data: SemanticModelUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SemanticModel).where(SemanticModel.id == model_id))
    model = result.scalar_one_or_none()
    if not model:
        raise HTTPException(status_code=404, detail="Semantic model not found")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(model, key, val)
    await db.commit()
    await db.refresh(model)
    return model


# ═══════════════════════════════════════════════════════════════════════════════
# Metrics CRUD
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{model_id}/metrics")
async def list_metrics(model_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SemanticMetric).where(SemanticMetric.semantic_model_id == model_id))
    return result.scalars().all()


@router.post("/{model_id}/metrics")
async def create_metric(model_id: str, data: MetricCreate, db: AsyncSession = Depends(get_db)):
    metric = SemanticMetric(semantic_model_id=model_id, **data.model_dump())
    db.add(metric)
    await db.commit()
    await db.refresh(metric)
    return metric


@router.patch("/{model_id}/metrics/{metric_id}")
async def update_metric(model_id: str, metric_id: str, data: MetricUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SemanticMetric).where(SemanticMetric.id == metric_id, SemanticMetric.semantic_model_id == model_id)
    )
    metric = result.scalar_one_or_none()
    if not metric:
        raise HTTPException(status_code=404, detail="Metric not found")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(metric, key, val)
    await db.commit()
    await db.refresh(metric)
    return metric


# ═══════════════════════════════════════════════════════════════════════════════
# Dimensions CRUD
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{model_id}/dimensions")
async def list_dimensions(model_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SemanticDimension).where(SemanticDimension.semantic_model_id == model_id))
    return result.scalars().all()


@router.post("/{model_id}/dimensions")
async def create_dimension(model_id: str, data: DimensionCreate, db: AsyncSession = Depends(get_db)):
    dim = SemanticDimension(semantic_model_id=model_id, **data.model_dump())
    db.add(dim)
    await db.commit()
    await db.refresh(dim)
    return dim


# ═══════════════════════════════════════════════════════════════════════════════
# Joins CRUD
# ═══════════════════════════════════════════════════════════════════════════════

@router.get("/{model_id}/joins")
async def list_joins(model_id: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SemanticJoin).where(SemanticJoin.semantic_model_id == model_id))
    return result.scalars().all()


@router.post("/{model_id}/joins")
async def create_join(model_id: str, data: JoinCreate, db: AsyncSession = Depends(get_db)):
    join = SemanticJoin(semantic_model_id=model_id, **data.model_dump())
    db.add(join)
    await db.commit()
    await db.refresh(join)
    return join


@router.patch("/{model_id}/joins/{join_id}")
async def update_join(model_id: str, join_id: str, data: JoinUpdate, db: AsyncSession = Depends(get_db)):
    result = await db.execute(
        select(SemanticJoin).where(SemanticJoin.id == join_id, SemanticJoin.semantic_model_id == model_id)
    )
    join = result.scalar_one_or_none()
    if not join:
        raise HTTPException(status_code=404, detail="Join not found")
    for key, val in data.model_dump(exclude_unset=True).items():
        setattr(join, key, val)
    await db.commit()
    await db.refresh(join)
    return join
