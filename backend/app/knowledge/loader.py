"""
知识库加载器：实现 Phase 1 的三个 Protocol（文件驱动）。
升级到 Phase 3 时，在 dependencies.py 中替换为 Qdrant 实现，此文件不改动。
"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

import sqlglot
import yaml

from app.config import get_settings
from app.protocols import (
    KnowledgeChunk,
    KnowledgeRetriever,
    TableSchema,
)

logger = logging.getLogger(__name__)


def _knowledge_dir() -> Path:
    return get_settings().knowledge_dir


# ── 方言规则加载 ──────────────────────────────────────────────────────────────────


@lru_cache
def load_dialect_rules() -> dict:
    """方言规则从 PDF 产品手册提取后存放于 knowledge/dialect_rules/。目录不存在时返回空默认。"""
    result: dict = {"unsupported": [], "syntax": [], "functions": {"supported": [], "unsupported": []}}

    rules_dir = _knowledge_dir() / "dialect_rules"
    if not rules_dir.exists():
        return result

    for yaml_file in rules_dir.glob("*.yaml"):
        try:
            with open(yaml_file, encoding="utf-8") as f:
                data = yaml.safe_load(f) or {}
            for key in ("unsupported", "syntax"):
                if key in data:
                    result[key].extend(data[key])
            if "functions" in data:
                fn = data["functions"]
                result["functions"]["supported"].extend(fn.get("supported", []))
                result["functions"]["unsupported"].extend(fn.get("unsupported", []))
        except Exception as e:
            logger.error("加载方言规则失败 %s: %s", yaml_file, e)

    return result


# ── SchemaRetriever Phase 1 实现 ──────────────────────────────────────────────────


class DbSchemaRetriever:
    """
    SchemaRetriever Phase 1 实现：从数据库记录中读取 DDL 并返回。
    需在调用时传入 session，由 chain 层注入。
    """

    def __init__(self, session):
        self._session = session

    async def retrieve(self, query: str, db_id: str) -> list[TableSchema]:
        """Phase 1: 返回指定 db_id 的完整 schema DDL（全量注入）。
        Phase 2: 解析 DDL 提取每个表的列名。"""
        from sqlalchemy import select

        from app.models.connection import DbConnection

        result = await self._session.execute(
            select(DbConnection).where(DbConnection.id == db_id, DbConnection.is_active.is_(True))
        )
        conn = result.scalar_one_or_none()
        if not conn or not conn.schema_ddl:
            return []

        # Phase 2: 尝试解析 DDL 为多个 TableSchema（含列名）
        schemas = _parse_ddl_to_schemas(conn.schema_ddl)
        if schemas:
            return schemas

        # 回退：将整个 DDL 作为一个 TableSchema 返回
        return [TableSchema(table_name="__all__", ddl=conn.schema_ddl, description=f"{conn.name} 数据库 Schema")]


def _parse_ddl_to_schemas(ddl_text: str) -> list[TableSchema]:
    """解析 DDL 文本，提取每个 CREATE TABLE 的表名和列名。"""
    schemas = []
    # 按分号分割语句
    statements = [s.strip() for s in ddl_text.split(";") if s.strip()]

    for stmt in statements:
        if not stmt.upper().startswith("CREATE TABLE"):
            continue

        # 尝试用 sqlglot 解析
        try:
            parsed = sqlglot.parse(stmt, dialect="mysql")
            if parsed and parsed[0]:
                create_stmt = parsed[0]
                if isinstance(create_stmt, sqlglot.exp.Create):
                    table = create_stmt.find(sqlglot.exp.Table)
                    if table and table.name:
                        table_name = table.name
                        # 提取列定义
                        schema = create_stmt.find(sqlglot.exp.Schema)
                        columns = []
                        if schema:
                            for col in schema.expressions:
                                if isinstance(col, sqlglot.exp.ColumnDef) and col.name:
                                    columns.append(col.name)
                        schemas.append(
                            TableSchema(
                                table_name=table_name,
                                ddl=stmt,
                                columns=columns,
                            )
                        )
                        continue
        except Exception:
            pass

        # 回退：正则提取表名和列名
        import re

        m = re.search(r"CREATE\s+TABLE\s+[`\"]?([^`\"(\s]+)[`\"]?\s*\((.+)\)", stmt, re.IGNORECASE | re.DOTALL)
        if m:
            table_name = m.group(1).strip()
            cols_text = m.group(2)
            columns = []
            for line in cols_text.split(","):
                parts = line.strip().split()
                if parts:
                    col_name = parts[0].strip("`\"'").lower()
                    if col_name and col_name not in ("primary", "unique", "index", "constraint", "foreign", "key"):
                        columns.append(col_name)
            schemas.append(
                TableSchema(
                    table_name=table_name,
                    ddl=stmt,
                    columns=columns,
                )
            )

    return schemas


# ── KnowledgeRetriever Phase 1 实现 ──────────────────────────────────────────────


class FileKnowledgeRetriever:
    """
    KnowledgeRetriever Phase 1 实现：从 faq.json 关键词匹配。
    Phase 3 升级：替换为 QdrantKnowledgeRetriever（RAG 向量检索）。
    """

    def __init__(self):
        self._faq: list[dict] | None = None

    def _load(self) -> list[dict]:
        if self._faq is not None:
            return self._faq

        faq_path = _knowledge_dir() / "docs" / "faq.json"
        self._faq = []

        if not faq_path.exists():
            logger.warning("faq.json 不存在: %s", faq_path)
            return self._faq

        with open(faq_path, encoding="utf-8") as f:
            self._faq = json.load(f) or []

        logger.info("加载 %d 条 FAQ 知识", len(self._faq))
        return self._faq

    async def retrieve(self, query: str, category: str | None = None) -> list[KnowledgeChunk]:
        """Phase 1: 关键词匹配（在问题和答案中搜索）。返回最多 3 条。"""
        faq = self._load()
        query_lower = query.lower()

        matched: list[KnowledgeChunk] = []
        for item in faq:
            # 按 category 过滤
            if category and item.get("category") != category:
                continue
            # 关键词匹配（问题或关键词字段中出现查询词）
            keywords = item.get("keywords", [])
            question = item.get("question", "").lower()
            answer = item.get("answer", "")
            if any(kw.lower() in query_lower for kw in keywords) or any(
                word in question for word in query_lower.split() if len(word) > 1
            ):
                matched.append(
                    KnowledgeChunk(
                        content=f"问题：{item['question']}\n\n答案：{answer}",
                        source=f"FAQ - {item.get('category', '通用')}",
                        category=item.get("category", ""),
                    )
                )
            if len(matched) >= 3:
                break

        return matched


assert isinstance(FileKnowledgeRetriever(), KnowledgeRetriever)
