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
    OrderRef,
    QueryIR,
    TimeRange,
)

logger = logging.getLogger(__name__)

PLANNER_SYSTEM_PROMPT = """你是一个查询计划器。你的任务是将用户的自然语言问题转换为结构化的查询计划（Query IR）。

## 输入
你会收到:
1. 用户的自然语言问题
2. 可用的业务指标（metrics）——你只能使用这些
3. 可用的维度（dimensions）——你只能使用这些
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
  "time_range": {"column": "orders.order_date", "start": "2025-01-01", "end_exclusive": "2026-01-01"},
  "order_by": [],
  "limit": null,
  "assumptions": ["'25年' 理解为 2025 自然年"],
  "unresolved": []
}
```

## 规则
1. **只使用提供的 metrics**。不要编造新的指标名或表达式。
2. **只使用提供的 dimensions**。不要编造维度名或列引用。
3. **只使用提供的 members** 作为过滤值。如果用户说的值和任何 member 都不匹配，放入 unresolved。
4. **时间表达式**:
   - "25年"/"2025年" → start: "2025-01-01", end_exclusive: "2026-01-01"
   - "全年"/"整年" → 一整年
   - "上半年" → start: "2025-01-01", end_exclusive: "2025-07-01"
   - "X月" → start: "2025-X-01", end_exclusive: 下个月1日
5. **query_type**:
   - 需要 SUM/COUNT/AVG 且无 GROUP BY → "aggregate"
   - 有 GROUP BY → "aggregate_rank"
   - 只是过滤/查看 → "simple_select"
6. **assumptions**: 记录你对用户问题含义的假设
7. **unresolved**: 记录无法确定的歧义（比如"华东"对应哪个字段有多个候选）

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
            return QueryIR.from_dict(ir_dict)
        except Exception as e:
            logger.error("Query planning failed: %s", e)
            return QueryIR(
                semantic_model_id=ctx.model.id,
                query_type="simple_select",
                unresolved=[Ambiguity(field="planning", candidates=[], question=f"查询计划生成失败: {e}")],
            )

    def _describe_metrics(self, ctx: SemanticContext) -> str:
        if not ctx.metrics:
            return "（无预定义指标）"
        lines = []
        for m in ctx.metrics:
            syns = ", ".join(m.synonyms or [])
            lines.append(f"- {m.name}: {m.expression}" + (f" (同义词: {syns})" if syns else ""))
        return "\n".join(lines)

    def _describe_dimensions(self, ctx: SemanticContext) -> str:
        if not ctx.dimensions:
            return "（无预定义维度）"
        lines = []
        for d in ctx.dimensions:
            syns = ", ".join(d.synonyms or [])
            lines.append(f"- {d.name}: {d.column_ref} ({d.data_type})" + (f" (同义词: {syns})" if syns else ""))
        return "\n".join(lines)

    def _describe_members(self, ctx: SemanticContext) -> str:
        if not ctx.members:
            return "（无预定义成员值）"
        lines = []
        for m in ctx.members:
            aliases = ", ".join(m.aliases or [])
            lines.append(f"- {m.display_value} → {m.raw_value}" + (f" (别名: {aliases})" if aliases else ""))
        return "\n".join(lines)

    def _describe_joins(self, ctx: SemanticContext) -> str:
        if not ctx.verified_joins:
            return "（无可信 JOIN）"
        lines = []
        for j in ctx.verified_joins:
            lines.append(f"- {j.left_table} ↔ {j.right_table}: {j.condition}")
        return "\n".join(lines)
