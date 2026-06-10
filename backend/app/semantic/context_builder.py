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
import os
import re
from dataclasses import dataclass, field

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.semantic.matcher import HybridSemanticMatcher, MatchResult, SemanticMatch
from app.semantic.models import (
    SemanticDimension,
    SemanticJoin,
    SemanticMember,
    SemanticMetric,
    SemanticModel,
)
from app.semantic.query_ir import Ambiguity
from app.semantic.schema_assets import SchemaAssets, build_schema_assets

logger = logging.getLogger(__name__)
_default_matcher: HybridSemanticMatcher | None = None
MAX_SCHEMA_FALLBACK_ASSETS = 80


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
    schema_catalog: dict[str, list[str]] = field(default_factory=dict)
    verified_joins: list[SemanticJoin] = field(default_factory=list)
    verified_examples: list[VerifiedExample] = field(default_factory=list)
    semantic_matches: dict[str, list[SemanticMatch]] = field(default_factory=dict)
    inferred_assets_used: bool = False
    confidence: float = 0.0
    ambiguities: list[Ambiguity] = field(default_factory=list)


class SemanticContextBuilder:
    """Builds a SemanticContext from a user question + database connection."""

    def __init__(self, session: AsyncSession, matcher: HybridSemanticMatcher | None = None):
        self._session = session
        self._matcher = matcher or self._get_default_matcher()

    async def build(
        self,
        question: str,
        db_connection_id: str,
        semantic_model_id: str | None = None,
    ) -> SemanticContext:
        """Build complete semantic context for a question."""
        ctx = SemanticContext()

        schema_assets = await self._load_schema_assets(db_connection_id)

        # 1. Select model scope
        ctx.model = await self._select_model(question, db_connection_id, semantic_model_id)
        if ctx.model is None:
            if schema_assets.model.table_names:
                ctx.model = schema_assets.model
                ctx.inferred_assets_used = True
            else:
                ctx.ambiguities.append(
                    Ambiguity(
                        field="semantic_model",
                        candidates=[],
                        question="未找到可查询的业务模型或 Schema，请先同步数据库表结构。",
                    )
                )
                return ctx
        else:
            schema_assets = await self._load_schema_assets(
                db_connection_id,
                ctx.model.table_names,
                ctx.model.id,
            )

        model_id = ctx.model.id

        # 2. Match metrics, dimensions, members — run in parallel
        metric_matches, dimension_matches, member_matches, examples = await asyncio.gather(
            self._match_metrics(question, model_id, schema_assets),
            self._match_dimensions(question, model_id, schema_assets),
            self._match_members(question, model_id),
            self._retrieve_examples(question, model_id),
        )
        metrics = self._select_matches(
            metric_matches,
            "metric",
            ctx,
            fallback_assets=schema_assets.metrics,
        )
        dimensions = self._select_matches(
            dimension_matches,
            "dimension",
            ctx,
            fallback_assets=schema_assets.dimensions,
        )
        metric_strength = metric_matches.matches[0].score if metric_matches.matches else 0.0
        dimension_strength = dimension_matches.matches[0].score if dimension_matches.matches else 0.0
        if dimension_strength >= 0.7 and (metric_strength < 0.7 or dimension_strength - metric_strength >= 0.15):
            metrics = []
        elif metric_strength >= 0.7 and (dimension_strength < 0.7 or metric_strength - dimension_strength >= 0.15):
            dimensions = []
        members = self._select_matches(member_matches, "member", ctx)
        ctx.metrics = metrics
        ctx.dimensions = dimensions
        ctx.members = members
        ctx.verified_examples = examples
        ctx.inferred_assets_used = ctx.inferred_assets_used or any(
            getattr(asset, "status", "") == "inferred" for asset in [*metrics, *dimensions]
        )
        ctx.dimensions = await self._augment_time_dimensions(
            question,
            model_id,
            metrics,
            dimensions,
            schema_assets.dimensions,
        )
        if members:
            member_dimension_ids = {member.dimension_id for member in members}
            known_dimension_ids = {dimension.id for dimension in ctx.dimensions}
            missing_dimension_ids = member_dimension_ids - known_dimension_ids
            if missing_dimension_ids:
                result = await self._session.execute(
                    select(SemanticDimension).where(
                        SemanticDimension.id.in_(missing_dimension_ids),
                        SemanticDimension.status == "verified",
                    )
                )
                ctx.dimensions.extend(result.scalars().all())

        # 3. Build focused schema from matched elements
        ctx.focused_schema = await self._build_focused_schema(
            db_connection_id,
            metrics,
            ctx.dimensions,
            ctx.model.table_names,
            ctx.model.primary_table,
        )
        ctx.schema_catalog = self._build_schema_catalog(db_connection_id, ctx.model.table_names)

        # 4. Select verified joins
        ctx.verified_joins = await self._select_joins(
            model_id,
            [t.name for t in ctx.focused_schema],
            schema_assets,
        )

        # 5. Compute confidence
        ctx.confidence = self._compute_confidence(ctx)

        return ctx

    def _get_default_matcher(self) -> HybridSemanticMatcher:
        global _default_matcher
        if _default_matcher is None:
            _default_matcher = HybridSemanticMatcher(embedder=self._get_embedder())
        return _default_matcher

    def _get_embedder(self):
        """Use semantic embeddings in production and deterministic lexical fallback in tests."""
        if os.getenv("TESTING"):
            return None
        try:
            from app.vector.embedder import get_embedder

            return get_embedder()
        except Exception as exc:
            logger.warning("Semantic matcher embedder unavailable: %s", exc)
            return None

    def _select_matches(
        self,
        result: MatchResult,
        asset_type: str,
        ctx: SemanticContext,
        fallback_assets: list | None = None,
    ) -> list:
        candidates = result.matches or [match for match in result.candidates if match.score >= 0.2]
        ctx.semantic_matches[asset_type] = result.candidates or result.matches
        if not candidates:
            # When lexical/embedding retrieval cannot bridge the user's words
            # to a new schema, expose a bounded set of real inferred assets to
            # the constrained planner instead of pretending there is no match.
            if fallback_assets:
                return fallback_assets[:MAX_SCHEMA_FALLBACK_ASSETS]
            return []

        exact = [match.asset for match in candidates if match.score >= 0.9]
        if exact:
            governed_exact = [asset for asset in exact if getattr(asset, "status", "") == "verified"]
            return governed_exact or exact

        if result.multi_intent:
            return [match.asset for match in candidates if match.lexical_score >= 0.75]

        # Retrieval narrows the candidate set; it should not create a user
        # ambiguity from weak cross-category character overlap. Only preserve
        # clarification for genuinely strong, close candidates.
        if result.ambiguous and candidates[0].score >= 0.7:
            labels = {
                "metric": "业务指标",
                "dimension": "分析维度",
                "member": "筛选值",
            }
            names = [
                str(getattr(match.asset, "name", "") or getattr(match.asset, "display_value", ""))
                for match in result.matches[:3]
            ]
            ctx.ambiguities.append(
                Ambiguity(
                    field=asset_type,
                    candidates=names,
                    question=f"{labels.get(asset_type, asset_type)}存在多个语义相近候选，请确认要使用哪一个",
                )
            )
            return []
        return [match.asset for match in candidates[:3]]

    async def _augment_time_dimensions(
        self,
        question: str,
        model_id: str,
        metrics: list[SemanticMetric],
        dimensions: list[SemanticDimension],
        inferred_dimensions: list | None = None,
    ) -> list[SemanticDimension]:
        """Add governed time dimensions when the question contains a time expression."""
        if not re.search(r"\d{2,4}年|全年|整年|上半年|下半年|\d{1,2}月|今年|去年|本月|上月", question):
            return dimensions

        source_tables = {table for metric in metrics for table in (metric.source_tables or [])}
        result = await self._session.execute(
            select(SemanticDimension).where(
                SemanticDimension.semantic_model_id == model_id,
                SemanticDimension.status == "verified",
                SemanticDimension.data_type == "time",
            )
        )
        existing_ids = {dimension.id for dimension in dimensions}
        compatible = []
        all_time_dimensions = [
            *result.scalars().all(),
            *[dimension for dimension in (inferred_dimensions or []) if getattr(dimension, "data_type", "") == "time"],
        ]
        for dimension in all_time_dimensions:
            table = (dimension.column_ref or "").split(".", 1)[0]
            if dimension.id not in existing_ids and (not source_tables or table in source_tables):
                compatible.append(dimension)
        return [*dimensions, *compatible]

    def _build_schema_catalog(self, db_id: str, model_tables: list[str]) -> dict[str, list[str]]:
        """Return complete columns for validation; never use pruned prompt context."""
        from app.agents.schema_graph import get_schema_graph

        graph = get_schema_graph(db_id)
        return {
            table_name: [column.name for column in graph.tables[table_name].columns]
            for table_name in model_tables
            if table_name in graph.tables
        }

    # ── Private helpers ──

    async def _select_model(self, question: str, db_id: str, model_id: str | None) -> SemanticModel | None:
        """Select or verify the semantic model."""
        if model_id:
            result = await self._session.execute(
                select(SemanticModel).where(
                    SemanticModel.id == model_id,
                    SemanticModel.db_connection_id == db_id,
                    SemanticModel.enabled_for_nl2sql.is_(True),
                )
            )
            return result.scalar_one_or_none()

        # Auto-select: find model with most term matches
        result = await self._session.execute(
            select(SemanticModel).where(
                SemanticModel.db_connection_id == db_id,
                SemanticModel.enabled_for_nl2sql.is_(True),
            )
        )
        models = result.scalars().all()
        if len(models) == 1:
            return models[0]
        if len(models) > 1:
            match_result = await self._matcher.match(question, list(models), asset_type="semantic_model")
            if match_result.matches and not match_result.ambiguous:
                return match_result.matches[0].asset
            logger.warning("Semantic model selection rejected due to low confidence or ambiguity")
        return None

    async def _match_metrics(self, question: str, model_id: str, schema_assets: SchemaAssets) -> MatchResult:
        """Match business terms to metric definitions."""
        result = await self._session.execute(
            select(SemanticMetric).where(
                SemanticMetric.semantic_model_id == model_id,
                SemanticMetric.status == "verified",
            )
        )
        metrics = self._merge_assets(
            list(result.scalars().all()),
            schema_assets.metrics,
            key=lambda metric: metric.expression.lower(),
        )
        return await self._matcher.match(question, metrics, asset_type="metric")

    async def _match_dimensions(self, question: str, model_id: str, schema_assets: SchemaAssets) -> MatchResult:
        """Match question terms to dimension definitions."""
        result = await self._session.execute(
            select(SemanticDimension).where(
                SemanticDimension.semantic_model_id == model_id,
                SemanticDimension.status == "verified",
            )
        )
        dimensions = self._merge_assets(
            list(result.scalars().all()),
            schema_assets.dimensions,
            key=lambda dimension: dimension.column_ref.lower(),
        )
        return await self._matcher.match(question, dimensions, asset_type="dimension")

    async def _match_members(self, question: str, model_id: str) -> MatchResult:
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
            return MatchResult()

        result = await self._session.execute(
            select(SemanticMember).where(
                SemanticMember.dimension_id.in_(dim_ids),
                SemanticMember.status == "verified",
            )
        )
        return await self._matcher.match(
            question,
            list(result.scalars().all()),
            asset_type="member",
            include_description=False,
            # Member values may contain customer data. Do not send them to an
            # external embedding provider from the online request path.
            use_embeddings=False,
        )

    async def _retrieve_examples(self, question: str, model_id: str) -> list[VerifiedExample]:
        """Retrieve verified NL2SQL examples similar to this question.

        Uses simple keyword matching for now. Phase 2 will add vector search.
        """
        # For now, return empty — example retrieval needs the nl2sql_cases table (Phase 4)
        return []

    async def _build_focused_schema(
        self,
        db_id: str,
        metrics: list[SemanticMetric],
        dimensions: list[SemanticDimension],
        model_tables: list[str],
        primary_table: str | None = None,
    ) -> list[FocusedTable]:
        """Build minimal schema with only relevant tables and columns."""
        from app.agents.schema_graph import build_schema_graph_from_connection, get_schema_graph
        from app.knowledge.loader import _parse_ddl_to_schemas
        from app.models.connection import DbConnection

        if not model_tables:
            return []

        graph = get_schema_graph(db_id)
        if not graph.tables:
            result = await self._session.execute(
                select(DbConnection.schema_ddl).where(
                    DbConnection.id == db_id,
                    DbConnection.is_active.is_(True),
                )
            )
            schema_ddl = result.scalar_one_or_none()
            if schema_ddl:
                graph = build_schema_graph_from_connection(
                    db_id,
                    _parse_ddl_to_schemas(schema_ddl),
                )
        focused = []

        # Collect relevant columns from metrics and dimensions
        relevant_columns: dict[str, set[str]] = {}  # table → {columns}
        for m in metrics:
            for t in m.source_tables or []:
                if t not in relevant_columns:
                    relevant_columns[t] = set()
                # Extract column references from expression
                import re

                for col_match in re.finditer(r"(\w+)\.(\w+)", m.expression):
                    if col_match.group(1) == t:
                        relevant_columns[t].add(col_match.group(2))

        for d in dimensions:
            parts = (d.column_ref or "").split(".")
            if len(parts) == 2:
                table, col = parts
                if table not in relevant_columns:
                    relevant_columns[table] = set()
                relevant_columns[table].add(col)

        selected_tables = set(relevant_columns)
        if not selected_tables and primary_table:
            selected_tables.add(primary_table)
        elif not selected_tables and len(model_tables) == 1:
            selected_tables.add(model_tables[0])

        for table_name in model_tables:
            if table_name not in selected_tables:
                continue
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

            focused.append(
                FocusedTable(
                    name=table_name,
                    columns=columns,
                    row_count=None,
                )
            )

        return focused

    async def _select_joins(
        self,
        model_id: str,
        table_names: list[str],
        schema_assets: SchemaAssets,
    ) -> list[SemanticJoin]:
        """Select verified joins between the focused tables."""
        result = await self._session.execute(
            select(SemanticJoin).where(
                SemanticJoin.semantic_model_id == model_id,
                SemanticJoin.status == "verified",
            )
        )
        all_joins = list(result.scalars().all())
        all_joins = self._merge_assets(
            all_joins,
            [join for join in schema_assets.joins if getattr(join, "confidence", 0.0) >= 0.9],
            key=lambda join: join.condition.lower(),
        )

        # Filter to joins where both tables are in the focused set
        table_set = set(table_names)
        return [j for j in all_joins if j.left_table in table_set and j.right_table in table_set]

    async def _load_schema_assets(
        self,
        db_id: str,
        table_names: list[str] | None = None,
        model_id: str | None = None,
    ) -> SchemaAssets:
        """Load or lazily build SchemaGraph and derive generic semantic assets."""
        from app.agents.schema_graph import build_schema_graph_from_connection, get_schema_graph

        effective_db_id = db_id
        if not effective_db_id and model_id:
            result = await self._session.execute(
                select(SemanticModel.db_connection_id).where(SemanticModel.id == model_id)
            )
            effective_db_id = result.scalar_one_or_none() or ""
        graph = get_schema_graph(effective_db_id)
        if not graph.tables:
            from app.knowledge.loader import _parse_ddl_to_schemas
            from app.models.connection import DbConnection

            result = await self._session.execute(
                select(DbConnection.schema_ddl).where(
                    DbConnection.id == effective_db_id,
                    DbConnection.is_active.is_(True),
                )
            )
            schema_ddl = result.scalar_one_or_none()
            if schema_ddl:
                graph = build_schema_graph_from_connection(
                    effective_db_id,
                    _parse_ddl_to_schemas(schema_ddl),
                )
        return build_schema_assets(
            effective_db_id,
            graph,
            table_names=table_names,
            model_id=model_id,
        )

    @staticmethod
    def _merge_assets(governed: list, inferred: list, *, key) -> list:
        """Governed assets override inferred assets describing the same field."""
        merged = {key(asset): asset for asset in inferred}
        merged.update({key(asset): asset for asset in governed})
        return list(merged.values())

    def _compute_confidence(self, ctx: SemanticContext) -> float:
        """Compute confidence from actual retrieval evidence and governance."""
        retrieval_scores = [matches[0].score for matches in ctx.semantic_matches.values() if matches]
        retrieval_confidence = sum(retrieval_scores) / len(retrieval_scores) if retrieval_scores else 0.0
        governance_bonus = 0.1 if ctx.model and not ctx.inferred_assets_used else 0.0
        governance_bonus += 0.05 if ctx.verified_joins else 0.0
        governance_bonus += 0.05 if ctx.schema_catalog else 0.0
        ambiguity_penalty = min(len(ctx.ambiguities) * 0.2, 0.6)
        inference_penalty = 0.1 if ctx.inferred_assets_used else 0.0
        return max(
            0.0,
            min(
                1.0,
                retrieval_confidence * 0.8 + governance_bonus - ambiguity_penalty - inference_penalty,
            ),
        )
