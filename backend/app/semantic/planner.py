"""Query Planner — converts NL question + SemanticContext into Query IR.

Uses LLM for NL understanding, but constrains the output to the structured
Query IR schema. The LLM only fills slots — it cannot hallucinate new metrics,
dimensions, or tables.
"""

from __future__ import annotations

import json
import logging

from app.semantic.context_builder import SemanticContext
from app.semantic.query_ir import (
    Ambiguity,
    DimensionRef,
    FilterRef,
    JoinRef,
    MetricRef,
    QueryIR,
)

logger = logging.getLogger(__name__)


class QueryPlanningError(RuntimeError):
    """Raised when the planning service fails instead of finding a user ambiguity."""


PLANNER_SYSTEM_PROMPT = """你是一个查询计划器。你的任务是将用户的自然语言问题转换为结构化的查询计划（Query IR）。

## 输入
你会收到:
1. 用户的自然语言问题
2. 可用的业务指标候选（metrics）——你只能使用这些，可以选择零个或多个
3. 可用的维度候选（dimensions）——你只能使用这些，可以选择零个或多个
4. 可用的维度成员值（members）——用于过滤条件
5. 可信的 JOIN 关系

## 输出格式
你必须返回一个 JSON 对象:

```json
{
  "query_type": "aggregate",
  "metrics": [{"name": "销售额", "expression": "SUM(orders.pay_amount)"}],
  "dimensions": [],
  "filters": [
    {"column": "orders.status", "operator": "IN", "value": ["paid", "shipped", "delivered"]}
  ],
  "time_range": {"column": "可用时间维度中的列引用", "start": "2025-01-01", "end_exclusive": "2026-01-01"},
  "required_tables": ["实际需要的表"],
  "joins": [],
  "order_by": [],
  "limit": null,
  "assumptions": ["'25年' 理解为 2025 自然年"],
  "unresolved": []
}
```

## 规则
1. **只使用提供的 metrics**。不要编造新的指标名或表达式。
2. **只使用提供的 dimensions**。不要编造维度名或列引用。
   - 候选召回不代表必须使用。用户只询问维度时，不要强行选择指标。
   - 用户只询问指标时，不要强行选择维度。
   - `status=inferred` 表示根据表字段自动推断，若使用必须在 assumptions 中说明。
   - 自动推断的金额、状态或数量含义无法从字段名确定时，放入 unresolved 请求确认。
3. **只使用提供的 members** 作为过滤值。如果用户说的值和任何 member 都不匹配，放入 unresolved。
4. **只使用提供的可信 JOIN**，并将实际需要的 JOIN 条件写入 joins。
5. **required_tables** 必须列出查询需要使用的全部表。
6. **时间表达式**:
   - time_range.column 必须从提供的 `data_type=time` 维度中选择。没有可用时间维度时放入 unresolved，禁止猜测字段。
   - "25年"/"2025年" → start: "2025-01-01", end_exclusive: "2026-01-01"
   - "全年"/"整年" → 一整年
   - "上半年" → start: "2025-01-01", end_exclusive: "2025-07-01"
   - "X月" → start: "2025-X-01", end_exclusive: 下个月1日
7. **query_type**:
   - 需要 SUM/COUNT/AVG 且无 GROUP BY → "aggregate"
   - 有 GROUP BY → "aggregate_rank"
   - 只是过滤/查看 → "simple_select"
8. **assumptions**: 记录你对用户问题含义的假设
9. **unresolved**: 记录无法确定的歧义（比如"华东"对应哪个字段有多个候选）。每一项必须是包含
   `field`、`candidates`、`question` 的 JSON 对象；没有歧义时返回空数组，禁止返回字符串。

只返回 JSON，不要输出任何其他内容。
"""


class QueryPlanner:
    """Converts NL question → Query IR using LLM, constrained by SemanticContext."""

    def __init__(self, llm_client):
        self._llm = llm_client

    async def plan(self, question: str, ctx: SemanticContext) -> QueryIR:
        """Generate a Query IR from the question and semantic context."""
        if ctx.model is None:
            return QueryIR(
                semantic_model_id="",
                query_type="simple_select",
                unresolved=[Ambiguity(field="semantic_model", candidates=[], question="未找到匹配的业务数据模型")],
            )
        if ctx.ambiguities:
            return QueryIR(
                semantic_model_id=ctx.model.id,
                query_type="simple_select",
                unresolved=list(ctx.ambiguities),
                confidence=ctx.confidence,
            )

        # Build the context for the LLM
        metrics_desc = self._describe_metrics(ctx)
        dimensions_desc = self._describe_dimensions(ctx)
        members_desc = self._describe_members(ctx)
        joins_desc = self._describe_joins(ctx)

        user_prompt = f"""## 用户问题
{question}

## 可用指标
{metrics_desc}

## 可用维度
{dimensions_desc}

## 可用成员值
{members_desc}

## 可信 JOIN
{joins_desc}

请生成 Query IR JSON:"""

        messages = [
            {"role": "system", "content": PLANNER_SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        try:
            content, _, _ = await self._llm.complete(messages, tools=None)
            # Strip markdown code fences if present
            content = content.strip()
            if content.startswith("```"):
                content = content.split("\n", 1)[1] if "\n" in content else content
                if content.endswith("```"):
                    content = content[:-3]
            ir_dict = json.loads(content)
            ir_dict["semantic_model_id"] = ctx.model.id
            query_ir = self._constrain_ir(QueryIR.from_dict(ir_dict), ctx)
            for ambiguity in ctx.ambiguities:
                if ambiguity not in query_ir.unresolved:
                    query_ir.unresolved.append(ambiguity)
            return query_ir
        except Exception as e:
            logger.exception("Query planning failed")
            raise QueryPlanningError("查询计划服务暂时不可用") from e

    def _describe_metrics(self, ctx: SemanticContext) -> str:
        if not ctx.metrics:
            return "（无预定义指标）"
        lines = []
        for m in ctx.metrics:
            syns = ", ".join(m.synonyms or [])
            details = [f"表达式: {m.expression}", f"来源表: {', '.join(m.source_tables or [])}"]
            details.append(f"治理状态: {getattr(m, 'status', 'verified')}")
            if m.default_filters:
                details.append(f"默认过滤: {json.dumps(m.default_filters, ensure_ascii=False)}")
            if m.allowed_dimensions:
                details.append(f"允许维度: {', '.join(m.allowed_dimensions)}")
            if syns:
                details.append(f"同义词: {syns}")
            evidence = self._semantic_evidence(ctx, "metric", m)
            if evidence:
                details.append(evidence)
            lines.append(f"- {m.name}: " + "; ".join(details))
        return "\n".join(lines)

    def _describe_dimensions(self, ctx: SemanticContext) -> str:
        if not ctx.dimensions:
            return "（无预定义维度）"
        lines = []
        for d in ctx.dimensions:
            syns = ", ".join(d.synonyms or [])
            evidence = self._semantic_evidence(ctx, "dimension", d)
            suffix = f" (同义词: {syns})" if syns else ""
            lines.append(
                f"- {d.name}: {d.column_ref} ({d.data_type}); 治理状态: {getattr(d, 'status', 'verified')}{suffix}"
                + (f"; {evidence}" if evidence else "")
            )
        return "\n".join(lines)

    def _describe_members(self, ctx: SemanticContext) -> str:
        if not ctx.members:
            return "（无预定义成员值）"
        lines = []
        dimensions = {d.id: d for d in ctx.dimensions}
        for m in ctx.members:
            aliases = ", ".join(m.aliases or [])
            dimension = dimensions.get(m.dimension_id)
            column = dimension.column_ref if dimension else "未知字段"
            lines.append(
                f"- {m.display_value} → {m.raw_value}; 字段: {column}"
                + (f" (别名: {aliases})" if aliases else "")
                + (
                    f"; {self._semantic_evidence(ctx, 'member', m)}"
                    if self._semantic_evidence(ctx, "member", m)
                    else ""
                )
            )
        return "\n".join(lines)

    def _semantic_evidence(self, ctx: SemanticContext, asset_type: str, asset) -> str:
        for match in ctx.semantic_matches.get(asset_type, []):
            if match.asset is asset:
                evidence = "、".join(match.evidence[:2])
                return f"匹配置信度: {match.score:.2f}" + (f"; 证据: {evidence}" if evidence else "")
        return ""

    def _describe_joins(self, ctx: SemanticContext) -> str:
        if not ctx.verified_joins:
            return "（无可信 JOIN）"
        lines = []
        for j in ctx.verified_joins:
            lines.append(f"- {j.left_table} ↔ {j.right_table}: {j.condition}")
        return "\n".join(lines)

    def _constrain_ir(self, query_ir: QueryIR, ctx: SemanticContext) -> QueryIR:
        """Replace model-generated semantic references with governed definitions."""
        metrics = {metric.name: metric for metric in ctx.metrics}
        dimensions = {dimension.name: dimension for dimension in ctx.dimensions}
        joins = {join.condition.strip().lower(): join for join in ctx.verified_joins}

        constrained_metrics = []
        for ref in query_ir.metrics:
            metric = metrics.get(ref.name)
            if metric is None:
                query_ir.unresolved.append(
                    Ambiguity(field="metric", candidates=list(metrics), question=f"指标“{ref.name}”未被语义模型定义")
                )
                continue
            constrained_metrics.append(MetricRef(name=metric.name, expression=metric.expression))
            if getattr(metric, "status", "") == "inferred":
                assumption = f"指标“{metric.name}”根据 Schema 字段自动推断，尚未经过业务口径确认"
                if assumption not in query_ir.assumptions:
                    query_ir.assumptions.append(assumption)
            for default_filter in metric.default_filters or []:
                try:
                    filter_ref = FilterRef(**default_filter)
                except TypeError:
                    continue
                if filter_ref not in query_ir.filters:
                    query_ir.filters.append(filter_ref)
        query_ir.metrics = constrained_metrics

        constrained_dimensions = []
        for ref in query_ir.dimensions:
            dimension = dimensions.get(ref.name)
            if dimension is None:
                query_ir.unresolved.append(
                    Ambiguity(
                        field="dimension",
                        candidates=list(dimensions),
                        question=f"维度“{ref.name}”未被语义模型定义",
                    )
                )
                continue
            constrained_dimensions.append(DimensionRef(name=dimension.name, column=dimension.column_ref))
            if getattr(dimension, "status", "") == "inferred":
                assumption = f"维度“{dimension.name}”根据 Schema 字段自动推断"
                if assumption not in query_ir.assumptions:
                    query_ir.assumptions.append(assumption)
        query_ir.dimensions = constrained_dimensions

        allowed_filter_columns = {dimension.column_ref for dimension in ctx.dimensions}
        governed_default_filters = {
            default_filter.get("column")
            for metric in ctx.metrics
            for default_filter in (metric.default_filters or [])
            if default_filter.get("column")
        }
        allowed_filter_columns.update(governed_default_filters)
        constrained_filters = []
        for filter_ref in query_ir.filters:
            if filter_ref.column not in allowed_filter_columns:
                query_ir.unresolved.append(
                    Ambiguity(
                        field="filter",
                        candidates=sorted(allowed_filter_columns),
                        question=f"过滤字段“{filter_ref.column}”未被语义模型定义",
                    )
                )
                continue
            constrained_filters.append(filter_ref)
        query_ir.filters = constrained_filters

        allowed_time_columns = {
            dimension.column_ref for dimension in ctx.dimensions if getattr(dimension, "data_type", "") == "time"
        }
        if query_ir.time_range and query_ir.time_range.column not in allowed_time_columns:
            query_ir.unresolved.append(
                Ambiguity(
                    field="time_range",
                    candidates=sorted(allowed_time_columns),
                    question=f"时间字段“{query_ir.time_range.column}”未被当前语义上下文定义",
                )
            )
            query_ir.time_range = None

        for metric_ref in query_ir.metrics:
            metric = metrics.get(metric_ref.name)
            if metric and metric.allowed_dimensions:
                disallowed = [
                    dimension.name
                    for dimension in query_ir.dimensions
                    if dimension.name not in metric.allowed_dimensions
                ]
                if disallowed:
                    query_ir.unresolved.append(
                        Ambiguity(
                            field="dimension",
                            candidates=metric.allowed_dimensions,
                            question=f"指标“{metric.name}”不允许按 {'、'.join(disallowed)} 分析",
                        )
                    )

        constrained_joins = []
        for ref in query_ir.joins:
            join = joins.get(ref.condition.strip().lower())
            if join is None:
                query_ir.unresolved.append(
                    Ambiguity(field="join", candidates=list(joins), question=f"JOIN“{ref.condition}”未经验证")
                )
                continue
            constrained_joins.append(JoinRef(condition=join.condition))
        query_ir.joins = constrained_joins

        # Never trust model-provided required_tables. Scope is derived only
        # from governed metrics, dimensions, filters, time ranges, and joins.
        tables: set[str] = set()
        for metric in query_ir.metrics:
            governed = metrics.get(metric.name)
            tables.update(governed.source_tables or [] if governed else [])
        for dimension in query_ir.dimensions:
            if "." in dimension.column:
                tables.add(dimension.column.split(".", 1)[0])
        for filter_ref in query_ir.filters:
            if "." in filter_ref.column:
                tables.add(filter_ref.column.split(".", 1)[0])
        if query_ir.time_range and "." in query_ir.time_range.column:
            tables.add(query_ir.time_range.column.split(".", 1)[0])
        for join_ref in query_ir.joins:
            governed = joins.get(join_ref.condition.strip().lower())
            if governed:
                tables.update([governed.left_table, governed.right_table])
        query_ir.required_tables = sorted(table for table in tables if table in (ctx.model.table_names or []))

        selected_join_conditions = {join.condition for join in query_ir.joins}
        for join in ctx.verified_joins:
            if (
                join.left_table in query_ir.required_tables
                and join.right_table in query_ir.required_tables
                and join.condition not in selected_join_conditions
            ):
                query_ir.joins.append(JoinRef(condition=join.condition))
        return query_ir
