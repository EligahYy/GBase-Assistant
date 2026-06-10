"""Generate fallback semantic assets from a connection's SchemaGraph.

Governed semantic models remain authoritative. These assets provide a usable
candidate layer for newly connected databases before business definitions have
been curated.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from app.agents.schema_graph import SchemaGraph


@dataclass
class SchemaSemanticModel:
    id: str
    db_connection_id: str
    name: str
    description: str
    table_names: list[str]
    primary_table: str | None
    enabled_for_nl2sql: bool = True
    prompt_hint: str | None = None


@dataclass
class SchemaMetric:
    id: str
    semantic_model_id: str
    name: str
    synonyms: list[str]
    expression: str
    source_tables: list[str]
    default_filters: list[dict] = field(default_factory=list)
    allowed_dimensions: list[str] = field(default_factory=list)
    description: str = ""
    status: str = "inferred"


@dataclass
class SchemaDimension:
    id: str
    semantic_model_id: str
    name: str
    column_ref: str
    synonyms: list[str]
    data_type: str
    time_granularities: list[str] | None = None
    hierarchy: list[str] | None = None
    status: str = "inferred"


@dataclass
class SchemaJoin:
    id: str
    semantic_model_id: str
    left_table: str
    right_table: str
    condition: str
    cardinality: str = "many_to_one"
    source: str = "schema_inferred"
    confidence: float = 0.7
    status: str = "inferred"


@dataclass
class SchemaAssets:
    model: SchemaSemanticModel
    metrics: list[SchemaMetric] = field(default_factory=list)
    dimensions: list[SchemaDimension] = field(default_factory=list)
    joins: list[SchemaJoin] = field(default_factory=list)


def build_schema_assets(
    db_connection_id: str,
    graph: SchemaGraph,
    *,
    table_names: list[str] | None = None,
    model_id: str | None = None,
) -> SchemaAssets:
    """Build safe, generic semantic candidates from parsed schema metadata."""
    selected_names = table_names or list(graph.tables)
    selected_tables = [graph.tables[name] for name in selected_names if name in graph.tables]
    inferred_model_id = model_id or f"schema:{db_connection_id}"
    model = SchemaSemanticModel(
        id=inferred_model_id,
        db_connection_id=db_connection_id,
        name="Schema 自动语义模型",
        description="根据表名、字段名、注释、类型和关系自动生成的候选语义模型",
        table_names=[table.name for table in selected_tables],
        primary_table=selected_tables[0].name if len(selected_tables) == 1 else None,
        prompt_hint="自动推断资产仅用于候选召回；不得猜测 Schema 中不存在的字段或关系。",
    )
    assets = SchemaAssets(model=model)

    for table in selected_tables:
        table_label = _clean_table_label(table.label or table.name)
        dimension_names = []
        primary_key = next((column for column in table.columns if column.role == "PRIMARY_KEY"), None)
        if primary_key:
            count_name = f"{table_label}数量"
            assets.metrics.append(
                SchemaMetric(
                    id=f"schema-metric:{table.name}:count",
                    semantic_model_id=inferred_model_id,
                    name=count_name,
                    synonyms=_dedupe(
                        [
                            f"{table_label}数",
                            f"{table_label}总数",
                            f"{table.name} count",
                            f"{table.name}数量",
                        ]
                    ),
                    expression=f"COUNT({table.name}.{primary_key.name})",
                    source_tables=[table.name],
                    description=f"根据主键 {table.name}.{primary_key.name} 自动推断的记录数量",
                )
            )

        for column in table.columns:
            name = column.label or column.name
            aliases = _dedupe([column.name, *column.aliases, column.comment])
            data_type = _dimension_type(column.role, column.data_type)
            dimension_names.append(name)
            assets.dimensions.append(
                SchemaDimension(
                    id=f"schema-dimension:{table.name}:{column.name}",
                    semantic_model_id=inferred_model_id,
                    name=name,
                    column_ref=f"{table.name}.{column.name}",
                    synonyms=aliases,
                    data_type=data_type,
                    time_granularities=["day", "month", "year"] if data_type == "time" else None,
                )
            )
            if column.role == "MEASURE":
                assets.metrics.append(
                    SchemaMetric(
                        id=f"schema-metric:{table.name}:{column.name}:sum",
                        semantic_model_id=inferred_model_id,
                        name=name,
                        synonyms=_dedupe([*aliases, f"{name}总额", f"{name}合计", f"总{name}"]),
                        expression=f"SUM({table.name}.{column.name})",
                        source_tables=[table.name],
                        description=f"根据数值字段 {table.name}.{column.name} 自动推断的求和指标",
                    )
                )

        for metric in assets.metrics:
            if table.name in metric.source_tables:
                metric.allowed_dimensions = list(dimension_names)

        for index, relationship in enumerate(table.relationships):
            target = relationship.get("target", "")
            condition = relationship.get("via", "")
            if target not in model.table_names or not condition:
                continue
            assets.joins.append(
                SchemaJoin(
                    id=f"schema-join:{table.name}:{target}:{index}",
                    semantic_model_id=inferred_model_id,
                    left_table=table.name,
                    right_table=target,
                    condition=condition,
                    confidence=float(relationship.get("confidence", 0.7)),
                )
            )

    assets.metrics = _dedupe_assets(assets.metrics, key=lambda metric: metric.expression.lower())
    assets.dimensions = _dedupe_assets(assets.dimensions, key=lambda dimension: dimension.column_ref.lower())
    assets.joins = _dedupe_assets(assets.joins, key=lambda join: join.condition.lower())
    _disambiguate_names(assets.metrics, source=lambda metric: metric.source_tables[0])
    _disambiguate_names(
        assets.dimensions,
        source=lambda dimension: dimension.column_ref.split(".", 1)[0],
    )
    return assets


def _clean_table_label(label: str) -> str:
    return label.removesuffix("表") or label


def _dimension_type(role: str, data_type: str) -> str:
    if role == "TIME_DIMENSION":
        return "time"
    if role == "ENUM":
        return "enum"
    if any(token in data_type.upper() for token in ("INT", "DECIMAL", "NUMERIC", "FLOAT", "DOUBLE", "REAL")):
        return "number"
    return "string"


def _dedupe(values: list[str]) -> list[str]:
    return list(dict.fromkeys(value.strip() for value in values if value and value.strip()))


def _dedupe_assets(values: list, *, key) -> list:
    result = {}
    for value in values:
        result.setdefault(key(value), value)
    return list(result.values())


def _disambiguate_names(values: list, *, source) -> None:
    groups: dict[str, list] = {}
    for value in values:
        groups.setdefault(value.name, []).append(value)
    for duplicates in groups.values():
        if len(duplicates) < 2:
            continue
        for value in duplicates:
            value.name = f"{value.name} [{source(value)}]"
