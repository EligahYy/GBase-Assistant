"""Semantic Context Builder — prepares structured context for NL2SQL.

Runs in parallel:
- Model scope selection
- Metric/dimension matching
- Member value linking
- FocusedSchema construction
- Verified JOIN selection
- Verified example retrieval

The model no longer needs to multi-turn explore the database.
It receives a pre-built SemanticContext and focuses on SQL generation.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.semantic.models import (
    SemanticDimension,
    SemanticJoin,
    SemanticMember,
    SemanticMetric,
    SemanticModel,
)
from app.semantic.query_ir import (
    Ambiguity,
    DimensionRef,
    FilterRef,
    JoinRef,
    MetricRef,
    OrderRef,
    QueryIR,
    TimeRange,
)

logger = logging.getLogger(__name__)


@dataclass
class FocusedTable:
    name: str
    columns: list[dict]  # [{name, type, role, label, enum_values, ...}]
    row_count: int | None = None


@dataclass
class VerifiedExample:
    question: str
    sql: str
    similarity: float = 0.0


@dataclass
class SemanticContext:
    model: SemanticModel | None = None
    metrics: list[SemanticMetric] = field(default_factory=list)
    dimensions: list[SemanticDimension] = field(default_factory=list)
    members: list[SemanticMember] = field(default_factory=list)
    focused_schema: list[FocusedTable] = field(default_factory=list)
    verified_joins: list[SemanticJoin] = field(default_factory=list)
    verified_examples: list[VerifiedExample] = field(default_factory=list)
    confidence: float = 0.0
    ambiguities: list[Ambiguity] = field(default_factory=list)


class SemanticContextBuilder:
    """Builds a SemanticContext from a user question + database connection."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def build(
        self,
        question: str,
        db_connection_id: str,
        semantic_model_id: str | None = None,
    ) -> SemanticContext:
        """Build complete semantic context for a question."""
        ctx = SemanticContext()

        # 1. Select model scope
        ctx.model = await self._select_model(question, db_connection_id, semantic_model_id)
        if ctx.model is None:
            ctx.ambiguities.append(Ambiguity(
                field="semantic_model",
                candidates=[],
                question="未找到匹配的业务数据模型，请选择一个可查询的数据集。",
            ))
            return ctx

        model_id = ctx.model.id

        # 2. Match metrics, dimensions, members — run in parallel
        metrics, dimensions, members, examples = await asyncio.gather(
            self._match_metrics(question, model_id),
            self._match_dimensions(question, model_id),
            self._match_members(question, model_id),
            self._retrieve_examples(question, model_id),
        )
        ctx.metrics = metrics
        ctx.dimensions = dimensions
        ctx.members = members
        ctx.verified_examples = examples

        # 3. Build focused schema from matched elements
        ctx.focused_schema = await self._build_focused_schema(
            db_connection_id, metrics, dimensions, ctx.model.table_names
        )

        # 4. Select verified joins
        ctx.verified_joins = await self._select_joins(
            model_id, [t.name for t in ctx.focused_schema]
        )

        # 5. Compute confidence
        ctx.confidence = self._compute_confidence(ctx)

        return ctx

    # ── Private helpers ──

    async def _select_model(
        self, question: str, db_id: str, model_id: str | None
    ) -> SemanticModel | None:
        """Select or verify the semantic model."""
        if model_id:
            result = await self._session.execute(
                select(SemanticModel).where(
                    SemanticModel.id == model_id,
                    SemanticModel.db_connection_id == db_id,
                    SemanticModel.enabled_for_nl2sql == True,
                )
            )
            return result.scalar_one_or_none()

        # Auto-select: find model with most term matches
        result = await self._session.execute(
            select(SemanticModel).where(
                SemanticModel.db_connection_id == db_id,
                SemanticModel.enabled_for_nl2sql == True,
            )
        )
        models = result.scalars().all()
        if len(models) == 1:
            return models[0]
        if len(models) > 1:
            # Pick the one whose description/name best matches the question
            question_lower = question.lower()
            best = max(models, key=lambda m: (
                sum(1 for w in question_lower if w in m.name.lower()) +
                sum(1 for w in question_lower if w in (m.description or "").lower())
            ))
            return best
        return None

    async def _match_metrics(self, question: str, model_id: str) -> list[SemanticMetric]:
        """Match business terms to metric definitions."""
        result = await self._session.execute(
            select(SemanticMetric).where(
                SemanticMetric.semantic_model_id == model_id,
                SemanticMetric.status == "verified",
            )
        )
        metrics = result.scalars().all()

        # Score each metric by name/synonym match
        scored = []
        for m in metrics:
            score = 0
            if m.name in question:
                score += 2
            for syn in (m.synonyms or []):
                if syn in question:
                    score += 1
            if m.description and any(w in question for w in (m.description or "").split()):
                score += 0.5
            if score > 0:
                scored.append((score, m))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [m for _, m in scored]

    async def _match_dimensions(self, question: str, model_id: str) -> list[SemanticDimension]:
        """Match question terms to dimension definitions."""
        result = await self._session.execute(
            select(SemanticDimension).where(
                SemanticDimension.semantic_model_id == model_id,
                SemanticDimension.status == "verified",
            )
        )
        dims = result.scalars().all()

        scored = []
        for d in dims:
            score = 0
            if d.name in question:
                score += 2
            for syn in (d.synonyms or []):
                if syn in question:
                    score += 1
            if score > 0:
                scored.append((score, d))

        scored.sort(key=lambda x: x[0], reverse=True)
        return [d for _, d in scored]

    async def _match_members(self, question: str, model_id: str) -> list[SemanticMember]:
        """Match member values (e.g., '华东', '已完成') to dimension members."""
        # Get dimension IDs for this model
        result = await self._session.execute(
            select(SemanticDimension.id).where(
                SemanticDimension.semantic_model_id == model_id,
                SemanticDimension.status == "verified",
            )
        )
        dim_ids = [r[0] for r in result.all()]

        if not dim_ids:
            return []

        result = await self._session.execute(
            select(SemanticMember).where(
                SemanticMember.dimension_id.in_(dim_ids),
                SemanticMember.status == "verified",
            )
        )
        members = result.scalars().all()

        matched = []
        for mem in members:
            aliases = [mem.display_value] + (mem.aliases or [])
            if any(a in question for a in aliases):
                matched.append(mem)

        return matched

    async def _retrieve_examples(self, question: str, model_id: str) -> list[VerifiedExample]:
        """Retrieve verified NL2SQL examples similar to this question.

        Uses simple keyword matching for now. Phase 2 will add vector search.
        """
        from app.models.conversation import Conversation

        # For now, return empty — example retrieval needs the nl2sql_cases table (Phase 4)
        return []

    async def _build_focused_schema(
        self,
        db_id: str,
        metrics: list[SemanticMetric],
        dimensions: list[SemanticDimension],
        model_tables: list[str],
    ) -> list[FocusedTable]:
        """Build minimal schema with only relevant tables and columns."""
        from app.agents.schema_graph import get_schema_graph

        if not model_tables:
            return []

        graph = get_schema_graph(db_id)
        focused = []

        # Collect relevant columns from metrics and dimensions
        relevant_columns: dict[str, set[str]] = {}  # table → {columns}
        for m in metrics:
            for t in (m.source_tables or []):
                if t not in relevant_columns:
                    relevant_columns[t] = set()
                # Extract column references from expression
                import re
                for col_match in re.finditer(r'(\w+)\.(\w+)', m.expression):
                    if col_match.group(1) == t:
                        relevant_columns[t].add(col_match.group(2))

        for d in dimensions:
            parts = (d.column_ref or "").split(".")
            if len(parts) == 2:
                table, col = parts
                if table not in relevant_columns:
                    relevant_columns[table] = set()
                relevant_columns[table].add(col)

        for table_name in model_tables:
            table_meta = graph.tables.get(table_name)
            if not table_meta:
                continue

            relevant_cols = relevant_columns.get(table_name, set())
            columns = []
            for col in table_meta.columns:
                col_info = {
                    "name": col.name,
                    "type": col.data_type,
                    "role": col.role,
                    "label": col.label or "",
                    "comment": col.comment or "",
                }
                if col.enum_values:
                    col_info["enum_values"] = col.enum_values
                # Always include primary keys and foreign keys
                if col.role in ("PRIMARY_KEY", "FOREIGN_KEY") or col.name in relevant_cols or not relevant_cols:
                    columns.append(col_info)

            focused.append(FocusedTable(
                name=table_name,
                columns=columns,
                row_count=None,
            ))

        return focused

    async def _select_joins(self, model_id: str, table_names: list[str]) -> list[SemanticJoin]:
        """Select verified joins between the focused tables."""
        result = await self._session.execute(
            select(SemanticJoin).where(
                SemanticJoin.semantic_model_id == model_id,
                SemanticJoin.status == "verified",
            )
        )
        all_joins = result.scalars().all()

        # Filter to joins where both tables are in the focused set
        table_set = set(table_names)
        return [
            j for j in all_joins
            if j.left_table in table_set and j.right_table in table_set
        ]

    def _compute_confidence(self, ctx: SemanticContext) -> float:
        """Compute overall confidence based on match quality."""
        score = 0.0
        if ctx.model:
            score += 0.2
        if ctx.metrics:
            score += min(len(ctx.metrics) * 0.15, 0.3)
        if ctx.dimensions:
            score += min(len(ctx.dimensions) * 0.1, 0.2)
        if ctx.members:
            score += 0.1
        if ctx.verified_joins:
            score += 0.1
        if ctx.verified_examples:
            score += 0.1
        return min(score, 1.0)
