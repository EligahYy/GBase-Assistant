"""Query IR — structured intermediate representation between NL and SQL.

Captures user intent before SQL generation, enabling:
- Deterministic verification that SQL faithfully implements user intent
- Display of natural-language query logic to the user
- Multi-turn conversation as Query IR modifications
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class MetricRef:
    name: str
    expression: str


@dataclass
class DimensionRef:
    name: str
    column: str


@dataclass
class FilterRef:
    column: str
    operator: str  # =, !=, IN, NOT IN, >, <, >=, <=, BETWEEN, LIKE
    value: str | list[str]


@dataclass
class TimeRange:
    column: str
    start: str
    end_exclusive: str


@dataclass
class OrderRef:
    target: str       # metric name or dimension name
    direction: str    # ASC | DESC


@dataclass
class JoinRef:
    condition: str


@dataclass
class Ambiguity:
    field: str        # Which part of the query is ambiguous
    candidates: list[str]
    question: str     # Clarification question for the user


@dataclass
class QueryIR:
    semantic_model_id: str
    query_type: str = "simple_select"  # simple_select | aggregate | aggregate_rank | time_series | compare | filter_only

    metrics: list[MetricRef] = field(default_factory=list)
    dimensions: list[DimensionRef] = field(default_factory=list)
    filters: list[FilterRef] = field(default_factory=list)
    time_range: TimeRange | None = None
    order_by: list[OrderRef] = field(default_factory=list)
    limit: int | None = None

    required_tables: list[str] = field(default_factory=list)
    joins: list[JoinRef] = field(default_factory=list)

    assumptions: list[str] = field(default_factory=list)
    unresolved: list[Ambiguity] = field(default_factory=list)
    confidence: float = 0.0

    def to_dict(self) -> dict:
        return {
            "semantic_model_id": self.semantic_model_id,
            "query_type": self.query_type,
            "metrics": [{"name": m.name, "expression": m.expression} for m in self.metrics],
            "dimensions": [{"name": d.name, "column": d.column} for d in self.dimensions],
            "filters": [{"column": f.column, "operator": f.operator, "value": f.value} for f in self.filters],
            "time_range": {"column": self.time_range.column, "start": self.time_range.start, "end_exclusive": self.time_range.end_exclusive} if self.time_range else None,
            "order_by": [{"target": o.target, "direction": o.direction} for o in self.order_by],
            "limit": self.limit,
            "required_tables": self.required_tables,
            "joins": [{"condition": j.condition} for j in self.joins],
            "assumptions": self.assumptions,
            "unresolved": [{"field": a.field, "candidates": a.candidates, "question": a.question} for a in self.unresolved],
            "confidence": self.confidence,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "QueryIR":
        return cls(
            semantic_model_id=d["semantic_model_id"],
            query_type=d.get("query_type", "simple_select"),
            metrics=[MetricRef(**m) for m in d.get("metrics", [])],
            dimensions=[DimensionRef(**dim) for dim in d.get("dimensions", [])],
            filters=[FilterRef(**f) for f in d.get("filters", [])],
            time_range=TimeRange(**d["time_range"]) if d.get("time_range") else None,
            order_by=[OrderRef(**o) for o in d.get("order_by", [])],
            limit=d.get("limit"),
            required_tables=d.get("required_tables", []),
            joins=[JoinRef(**j) for j in d.get("joins", [])],
            assumptions=d.get("assumptions", []),
            unresolved=[Ambiguity(**a) for a in d.get("unresolved", [])],
            confidence=d.get("confidence", 0.0),
        )

    def to_natural_language(self) -> str:
        """Generate human-readable description of this query."""
        parts = []

        if self.metrics:
            metrics_str = "、".join(f"{m.name}({m.expression})" for m in self.metrics)
            parts.append(f"指标: {metrics_str}")

        if self.dimensions:
            dims_str = "、".join(d.name for d in self.dimensions)
            parts.append(f"维度: {dims_str}")

        if self.time_range:
            parts.append(f"时间范围: {self.time_range.start} 至 {self.time_range.end_exclusive}")

        if self.filters:
            for f in self.filters:
                parts.append(f"过滤: {f.column} {f.operator} {f.value}")

        if self.joins:
            for j in self.joins:
                parts.append(f"关联: {j.condition}")

        if self.order_by:
            for o in self.order_by:
                parts.append(f"排序: {o.target} {'降序' if o.direction == 'DESC' else '升序'}")

        if self.limit:
            parts.append(f"条数: 前 {self.limit}")

        return "\n".join(f"- {p}" for p in parts)
