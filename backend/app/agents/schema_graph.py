"""Schema Knowledge Graph — DDL语义解析、别名生成、关系推断、多策略检索。

为 Schema Grounding Agent 提供结构化的数据库元数据。
"""

from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
# Data Classes
# ═══════════════════════════════════════════════════════════════════


@dataclass
class ColumnMeta:
    """列的语义元数据。"""

    name: str
    data_type: str
    role: str = "UNKNOWN"  # PRIMARY_KEY | MEASURE | TIME_DIMENSION | ENUM | FOREIGN_KEY | UNKNOWN
    label: str = ""  # 中文标签
    aliases: list[str] = field(default_factory=list)
    comment: str = ""
    enum_values: dict | None = None

    def to_dict(self) -> dict:
        d = {
            "name": self.name,
            "type": self.data_type,
            "role": self.role,
            "label": self.label,
            "aliases": self.aliases,
        }
        if self.comment:
            d["comment"] = self.comment
        if self.enum_values:
            d["enum_values"] = self.enum_values
        return d

    @classmethod
    def from_dict(cls, d: dict) -> ColumnMeta:
        return cls(
            name=d["name"],
            data_type=d["type"],
            role=d.get("role", "UNKNOWN"),
            label=d.get("label", ""),
            aliases=d.get("aliases", []),
            comment=d.get("comment", ""),
            enum_values=d.get("enum_values"),
        )


@dataclass
class TableMeta:
    """表的语义元数据。"""

    name: str
    label: str = ""
    aliases: list[str] = field(default_factory=list)
    columns: list[ColumnMeta] = field(default_factory=list)
    distribution: str = ""
    relationships: list[dict] = field(default_factory=list)  # {target, via, type, confidence}

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "label": self.label,
            "aliases": self.aliases,
            "columns": [c.to_dict() for c in self.columns],
            "distribution": self.distribution,
            "relationships": self.relationships,
        }

    @classmethod
    def from_dict(cls, d: dict) -> TableMeta:
        return cls(
            name=d["name"],
            label=d.get("label", ""),
            aliases=d.get("aliases", []),
            columns=[ColumnMeta.from_dict(c) for c in d.get("columns", [])],
            distribution=d.get("distribution", ""),
            relationships=d.get("relationships", []),
        )


# ═══════════════════════════════════════════════════════════════════
# DDL Parser
# ═══════════════════════════════════════════════════════════════════


class DDLParser:
    """从 CREATE TABLE DDL 中提取结构化元数据。

    使用 sqlglot 解析标准 DDL，regex 回退处理 GBase 特有语法。
    """

    # 列角色推断规则
    _MEASURE_TYPES = {
        "DECIMAL",
        "NUMERIC",
        "FLOAT",
        "DOUBLE",
        "INT",
        "INTEGER",
        "BIGINT",
        "SMALLINT",
        "TINYINT",
        "REAL",
    }
    _TIME_TYPES = {"DATE", "DATETIME", "TIMESTAMP", "TIME"}

    @staticmethod
    def parse_ddl(ddl: str) -> TableMeta | None:
        """解析单条 CREATE TABLE DDL，返回 TableMeta。"""
        # 提取表名
        table_match = re.search(
            r'CREATE\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?[`"\[\]]?(\w+)[`"\[\]]?', ddl, re.IGNORECASE
        )
        if not table_match:
            return None
        table_name = table_match.group(1)

        # Better approach: split by commas between the outermost parentheses
        columns_section = DDLParser._extract_columns_section(ddl)
        if not columns_section:
            return None

        columns = DDLParser._parse_columns(columns_section)

        # 提取 DISTRIBUTED BY / REPLICATED
        distribution = ""
        dist_match = re.search(r"DISTRIBUTED\s+BY\s*\(([^)]+)\)", ddl, re.IGNORECASE)
        if dist_match:
            distribution = f"DISTRIBUTED BY({dist_match.group(1)})"
        elif re.search(r"REPLICATED", ddl, re.IGNORECASE):
            distribution = "REPLICATED"

        return TableMeta(
            name=table_name,
            label=DDLParser._infer_table_label(table_name),
            aliases=DDLParser._generate_table_aliases(table_name),
            columns=columns,
            distribution=distribution,
        )

    @staticmethod
    def _extract_columns_section(ddl: str) -> str | None:
        """提取括号内的列定义部分。"""
        # Find the first '(' after CREATE TABLE ... and match its closing ')'
        start = ddl.find("(")
        if start == -1:
            return None
        depth = 0
        for i in range(start, len(ddl)):
            if ddl[i] == "(":
                depth += 1
            elif ddl[i] == ")":
                depth -= 1
                if depth == 0:
                    return ddl[start + 1 : i]
        return None

    @staticmethod
    def _parse_columns(columns_text: str) -> list[ColumnMeta]:
        """解析列定义文本，提取每列的元数据。"""
        columns = []
        # Split by comma, but not commas inside parentheses
        col_defs = DDLParser._split_column_defs(columns_text)

        for col_def in col_defs:
            col_def = col_def.strip()
            # Skip constraints (PRIMARY KEY, INDEX, etc.)
            if re.match(r"^\s*(PRIMARY|UNIQUE|INDEX|KEY|CONSTRAINT|FOREIGN|CHECK)\s", col_def, re.IGNORECASE):
                continue
            if not col_def:
                continue

            col_meta = DDLParser._parse_single_column(col_def)
            if col_meta:
                columns.append(col_meta)

        return columns

    @staticmethod
    def _split_column_defs(columns_text: str) -> list[str]:
        """Split column definitions by comma, respecting nested parentheses."""
        parts = []
        depth = 0
        current = ""
        for ch in columns_text:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
            if ch == "," and depth == 0:
                parts.append(current)
                current = ""
            else:
                current += ch
        if current.strip():
            parts.append(current)
        return parts

    @staticmethod
    def _parse_single_column(col_def: str) -> ColumnMeta | None:
        """解析单个列定义。"""
        # Pattern: `name` TYPE[(params)] [NOT NULL] [DEFAULT ...] [COMMENT '...']
        match = re.match(
            r'[`"\[]?(\w+)[`"\]]?\s+'  # column name
            r"(\w+)"  # type keyword
            r"(\([^)]*\))?"  # optional type params
            r"(.*)",  # rest (NOT NULL, DEFAULT, COMMENT, etc.)
            col_def,
            re.DOTALL | re.IGNORECASE,
        )
        if not match:
            return None

        col_name = match.group(1)
        type_keyword = match.group(2).upper()
        type_params = match.group(3) or ""
        rest = match.group(4)

        # Extract COMMENT
        comment = ""
        comment_match = re.search(r"COMMENT\s+['\"](.+?)['\"]", rest, re.IGNORECASE)
        if comment_match:
            comment = comment_match.group(1)

        # Infer role
        role = DDLParser._infer_role(col_def, col_name, type_keyword, comment, rest)

        # Extract enum values from COMMENT (e.g., "状态:1待支付2已支付3已取消")
        enum_values = None
        if role == "ENUM" and comment:
            enum_values = DDLParser._extract_enum_values(comment)

        # Generate label
        label = DDLParser._extract_label(col_name, comment)

        # Generate aliases
        aliases = DDLParser._generate_column_aliases(col_name, comment, label)

        return ColumnMeta(
            name=col_name,
            data_type=f"{type_keyword}{type_params}",
            role=role,
            label=label,
            aliases=aliases,
            comment=comment,
            enum_values=enum_values,
        )

    @staticmethod
    def _infer_role(col_def: str, col_name: str, type_keyword: str, comment: str, rest: str) -> str:
        """推断列的语义角色。"""
        # PRIMARY KEY (explicit)
        if re.search(r"PRIMARY\s+KEY", col_def, re.IGNORECASE):
            return "PRIMARY_KEY"

        # TIME_DIMENSION: databases frequently store timestamps in TEXT/VARCHAR
        # columns, so use stable naming conventions in addition to SQL types.
        if type_keyword in DDLParser._TIME_TYPES or re.search(
            r"(^|_)(date|time|timestamp|datetime)$|_at$",
            col_name,
            re.IGNORECASE,
        ):
            return "TIME_DIMENSION"

        # ENUM: TINYINT/SMALLINT with enum-like COMMENT (before MEASURE check)
        if type_keyword in ("TINYINT", "SMALLINT", "INT", "INTEGER") and comment:
            # Patterns: "1待支付2已支付", "1:待支付", "1-待支付"
            if re.search(r"\d+\s*[:：\-]?\s*\D", comment):
                return "ENUM"

        # MEASURE: numeric types that are often aggregated
        if type_keyword in DDLParser._MEASURE_TYPES:
            # Check if it looks like an ID or code
            if re.search(r"(id|no|code)$", col_name, re.IGNORECASE):
                return "FOREIGN_KEY"
            return "MEASURE"

        # FOREIGN_KEY: naming convention
        if re.search(r"(_id|_no|_code)$", col_name, re.IGNORECASE):
            return "FOREIGN_KEY"

        return "UNKNOWN"

    @staticmethod
    def _extract_enum_values(comment: str) -> dict | None:
        """从 COMMENT 中提取枚举值映射。

        支持格式:
        - "1:待支付 2:已支付 3:已取消"  (冒号分隔)
        - "1待支付2已支付3已取消"       (数字+文字直接连接)
        - "1-待支付 2-已支付"          (破折号分隔)
        """
        # Try format with separator first: "1:待支付 2:已支付"
        pairs = re.findall(r"(\d+)\s*[:：\-]\s*(\S+)", comment)
        if pairs:
            return {int(k): v for k, v in pairs}
        # Try format without separator: "1待支付2已支付3已取消"
        pairs = re.findall(r"(\d+)([^\d]+)", comment)
        if pairs:
            return {int(k): v.strip() for k, v in pairs}
        return None

    @staticmethod
    def _extract_label(col_name: str, comment: str) -> str:
        """提取列的中文标签。优先用 COMMENT，否则从列名推断。"""
        if comment:
            # Use COMMENT up to first colon/enum separator
            label = re.split(r"[:：\d]", comment)[0].strip()
            if label:
                return label
        return DDLParser._name_to_label(col_name)

    @staticmethod
    def _infer_table_label(table_name: str) -> str:
        """从表名推断中文标签。"""
        # Common patterns
        label_map = {
            "user": "用户表",
            "users": "用户表",
            "order": "订单表",
            "orders": "订单表",
            "product": "产品表",
            "products": "产品表",
            "customer": "客户表",
            "customers": "客户表",
            "employee": "员工表",
            "employees": "员工表",
            "sale": "销售表",
            "sales": "销售表",
            "inventory": "库存表",
            "payment": "支付表",
            "payments": "支付表",
            "log": "日志表",
            "logs": "日志表",
            "config": "配置表",
        }
        for key, label in label_map.items():
            if key in table_name.lower():
                return label
        return table_name

    @staticmethod
    def _generate_table_aliases(table_name: str) -> list[str]:
        """生成表名别名。"""
        aliases = [table_name]
        # Remove underscores
        no_underscore = table_name.replace("_", "")
        if no_underscore != table_name:
            aliases.append(no_underscore)
        return aliases

    @staticmethod
    def _generate_column_aliases(col_name: str, comment: str, label: str) -> list[str]:
        """生成列别名。"""
        aliases = [col_name]
        if label and label != col_name:
            aliases.append(label)
        # Remove prefix (e.g., order_amount -> amount)
        if "_" in col_name:
            prefix_removed = col_name.split("_", 1)[-1]
            if prefix_removed != col_name:
                aliases.append(prefix_removed)
        # Extract Chinese word segments from label
        if label:
            # Strip parenthetical content first: "订单金额(元)" → "订单金额"
            stripped = re.sub(r"[\(（].*?[\)）]", "", label).strip()
            if stripped and stripped not in aliases:
                aliases.append(stripped)
            # Extract 2-char sliding windows from stripped label
            if len(stripped) >= 2:
                for i in range(len(stripped) - 1):
                    chunk = stripped[i : i + 2]
                    if chunk not in aliases:
                        aliases.append(chunk)
        return aliases

    @staticmethod
    def _name_to_label(name: str) -> str:
        """简单的中文标签推断（snake_case → 中文）。"""
        common_words = {
            "id": "编号",
            "name": "名称",
            "amount": "金额",
            "price": "价格",
            "time": "时间",
            "date": "日期",
            "status": "状态",
            "type": "类型",
            "code": "编码",
            "no": "编号",
            "desc": "描述",
            "remark": "备注",
            "count": "数量",
            "total": "总计",
            "user": "用户",
            "order": "订单",
            "product": "产品",
            "customer": "客户",
        }
        if name.lower() in common_words:
            return common_words[name.lower()]
        # Capitalize first letter for display
        return name.replace("_", " ").title()


# ═══════════════════════════════════════════════════════════════════
# Relation Inferrer
# ═══════════════════════════════════════════════════════════════════


class RelationInferrer:
    """推断表之间的 JOIN 关系。"""

    @staticmethod
    def infer(tables: list[TableMeta]) -> list[dict]:
        """在所有表中推断外键关系。返回关系列表。"""
        all_relationships = []

        # Build index: column_name → list of (table_name, column)
        fk_index: dict[str, list[tuple[str, ColumnMeta]]] = {}
        for table in tables:
            for col in table.columns:
                if col.role == "FOREIGN_KEY" or col.role == "PRIMARY_KEY":
                    key = col.name.lower()
                    if key not in fk_index:
                        fk_index[key] = []
                    fk_index[key].append((table.name, col))

        # Match FK columns to PK columns in other tables
        for table in tables:
            for col in table.columns:
                if col.role != "FOREIGN_KEY":
                    continue

                col_name = col.name.lower()
                # Try to find target: remove _id/_no/_code suffix, find matching table
                base_name = re.sub(r"(_id|_no|_code)$", "", col_name)

                # Look for matching table
                for other_table in tables:
                    if other_table.name == table.name:
                        continue
                    # Match by table name
                    if base_name in other_table.name.lower():
                        # Find matching column in target table
                        target_col = None
                        for oc in other_table.columns:
                            if oc.role == "PRIMARY_KEY" and oc.name.lower() in (col_name, "id"):
                                target_col = oc
                                break
                        if not target_col:
                            # Just use first PK or 'id' column
                            for oc in other_table.columns:
                                if oc.name.lower() == "id":
                                    target_col = oc
                                    break

                        via = f"{table.name}.{col.name} = {other_table.name}.{target_col.name if target_col else 'id'}"
                        rel = {
                            "source": table.name,
                            "target": other_table.name,
                            "via": via,
                            "type": "MANY_TO_ONE",
                            "confidence": 0.7,
                        }
                        # Avoid duplicates
                        if not any(r["via"] == via for r in all_relationships):
                            all_relationships.append(rel)
                        # Also add to table metadata
                        table.relationships.append(rel)

        return all_relationships


# ═══════════════════════════════════════════════════════════════════
# Schema Graph Builder & Store
# ═══════════════════════════════════════════════════════════════════


class SchemaGraph:
    """Schema Knowledge Graph — 构建、存储、检索。

    从 TableSchema 列表（fetch_schema 的输出）构建语义知识图谱。
    """

    def __init__(self, db_id: str):
        self.db_id = db_id
        self.tables: dict[str, TableMeta] = {}
        # 多策略索引
        self._exact_index: dict[str, list[tuple[str, str, str]]] = {}  # term → [(table, col, type)]
        self._built = False

    def build_from_schemas(self, schemas: list) -> None:
        """从 TableSchema 列表构建图谱。

        Args:
            schemas: TableSchema 对象列表（来自 native_connector.fetch_schema）
                每个有 table_name, ddl, description, columns 属性
        """
        from app.protocols import TableSchema

        tables_list = []
        for schema in schemas:
            if isinstance(schema, TableSchema):
                ddl = schema.ddl
            elif hasattr(schema, "ddl"):
                ddl = schema.ddl
            else:
                continue

            if not ddl or not isinstance(ddl, str):
                continue

            table_meta = DDLParser.parse_ddl(ddl)
            if not table_meta:
                continue

            # Apply description if available
            if hasattr(schema, "description") and schema.description and not table_meta.label:
                table_meta.label = schema.description

            tables_list.append(table_meta)
            self.tables[table_meta.name] = table_meta

        # Infer relationships
        relationships = RelationInferrer.infer(tables_list)
        logger.info(
            "SchemaGraph[%s]: built %d tables, %d relationships", self.db_id, len(tables_list), len(relationships)
        )

        # Build exact match index
        self._build_exact_index()
        self._built = True

    def _build_exact_index(self) -> None:
        """构建精确匹配索引。"""
        self._exact_index.clear()
        for table in self.tables.values():
            # Index table name + aliases
            for alias in [table.name] + table.aliases:
                key = alias.lower()
                if key not in self._exact_index:
                    self._exact_index[key] = []
                self._exact_index[key].append((table.name, "*", "table"))

            # Index column name + aliases
            for col in table.columns:
                for alias in [col.name] + col.aliases:
                    key = alias.lower()
                    if key not in self._exact_index:
                        self._exact_index[key] = []
                    self._exact_index[key].append((table.name, col.name, col.role))

    # ── Retrieval ──

    def exact_match(self, query: str) -> list[dict]:
        """L1: 精确匹配。在所有表名/列名/别名中查找 term。"""
        results = []
        if not self._built:
            return results

        # Tokenize query into words
        words = re.findall(r"[一-鿿\w]+", query)
        seen = set()

        for word in words:
            key = word.lower()
            if key in self._exact_index:
                for table_name, col_name, role in self._exact_index[key]:
                    entry = (table_name, col_name)
                    if entry not in seen:
                        seen.add(entry)
                        results.append(
                            {
                                "term": word,
                                "table": table_name,
                                "column": col_name,
                                "role": role,
                                "score": 1.0,
                                "source": "exact",
                            }
                        )

        return results

    def find_join_path(self, table_a: str, table_b: str) -> list[dict] | None:
        """L3: 查找两个表之间的 JOIN 路径（BFS 最短路径）。"""
        if table_a not in self.tables or table_b not in self.tables:
            return None

        # Build adjacency from relationships
        graph: dict[str, list[tuple[str, dict]]] = {}
        for table in self.tables.values():
            graph.setdefault(table.name, [])
            for rel in table.relationships:
                target = rel["target"]
                graph.setdefault(target, [])
                graph[table.name].append((target, rel))
                # Bidirectional
                rev_rel = {
                    "source": target,
                    "target": table.name,
                    "via": rel["via"],
                    "type": "ONE_TO_MANY",
                    "confidence": rel["confidence"],
                }
                graph[target].append((table.name, rev_rel))

        if table_a not in graph:
            return None

        # BFS
        from collections import deque

        queue = deque([(table_a, [])])
        visited = {table_a}

        while queue:
            current, path = queue.popleft()
            if current == table_b:
                return path
            for neighbor, rel in graph.get(current, []):
                if neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + [rel]))

        return None

    def validate_mapping(self, tables: list[str], columns: dict[str, list[str]]) -> dict:
        """验证 Semantic Mapper 输出的表/列映射是否真实存在。

        Returns:
            {"valid": bool, "errors": [str], "warnings": [str]}
        """
        errors = []
        warnings = []

        for table_name in tables:
            if table_name not in self.tables:
                errors.append(f"表 '{table_name}' 不存在于 Schema 中")
                continue

            table = self.tables[table_name]
            table_cols = {c.name for c in table.columns}
            mapped_cols = columns.get(table_name, [])

            for col_name in mapped_cols:
                if col_name not in table_cols:
                    errors.append(f"列 '{table_name}.{col_name}' 不存在")

            # 检查是否有被映射但未指定任何列的情况
            if not mapped_cols:
                warnings.append(f"表 '{table_name}' 被映射但未指定任何列")

        return {
            "valid": len(errors) == 0,
            "errors": errors,
            "warnings": warnings,
        }

    def get_context_for_tables(self, table_names: list[str]) -> dict:
        """获取指定表的完整上下文（列、关系、分布键）。"""
        context = {"tables": {}, "relationships": []}
        seen_rels = set()

        for name in table_names:
            if name in self.tables:
                table = self.tables[name]
                context["tables"][name] = {
                    "label": table.label,
                    "distribution": table.distribution,
                    "columns": {c.name: {"type": c.data_type, "role": c.role, "label": c.label} for c in table.columns},
                }
                for rel in table.relationships:
                    key = rel["via"]
                    if key not in seen_rels:
                        seen_rels.add(key)
                        context["relationships"].append(rel)

        return context

    # ── Persistence ──

    def to_dict(self) -> dict:
        return {
            "db_id": self.db_id,
            "tables": [t.to_dict() for t in self.tables.values()],
        }

    def save(self, data_dir: str | None = None) -> str:
        """保存到 JSON 文件。返回文件路径。"""
        if data_dir is None:
            data_dir = str(Path(__file__).parent.parent.parent / "data" / "schema_graph")
        Path(data_dir).mkdir(parents=True, exist_ok=True)
        filepath = f"{data_dir}/{self.db_id}.json"
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(self.to_dict(), f, ensure_ascii=False, indent=2)
        logger.info("SchemaGraph[%s]: saved to %s", self.db_id, filepath)
        return filepath

    @classmethod
    def load(cls, db_id: str, data_dir: str | None = None) -> SchemaGraph | None:
        """从 JSON 文件加载。"""
        if data_dir is None:
            data_dir = str(Path(__file__).parent.parent.parent / "data" / "schema_graph")
        filepath = f"{data_dir}/{db_id}.json"
        if not Path(filepath).exists():
            return None

        with open(filepath, encoding="utf-8") as f:
            data = json.load(f)

        graph = cls(db_id=db_id)
        for t_data in data.get("tables", []):
            table = TableMeta.from_dict(t_data)
            graph.tables[table.name] = table

        graph._build_exact_index()
        graph._built = True
        logger.info("SchemaGraph[%s]: loaded from %s (%d tables)", db_id, filepath, len(graph.tables))
        return graph


# ═══════════════════════════════════════════════════════════════════
# Factory
# ═══════════════════════════════════════════════════════════════════

_graph_instances: dict[str, SchemaGraph] = {}


def get_schema_graph(db_id: str) -> SchemaGraph:
    """获取或创建 SchemaGraph 实例（按 db_id 缓存）。"""
    if db_id not in _graph_instances:
        # 尝试从磁盘加载
        graph = SchemaGraph.load(db_id)
        if graph is None:
            graph = SchemaGraph(db_id=db_id)
        _graph_instances[db_id] = graph
    return _graph_instances[db_id]


def build_schema_graph_from_connection(db_id: str, schemas: list) -> SchemaGraph:
    """从连接获取的 Schema 构建图谱，并持久化。"""
    graph = SchemaGraph(db_id=db_id)
    graph.build_from_schemas(schemas)
    graph.save()
    _graph_instances[db_id] = graph
    return graph
