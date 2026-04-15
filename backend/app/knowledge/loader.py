"""
知识库加载器：实现 Phase 1 的三个 Protocol（文件驱动）。
升级到 Phase 3 时，在 dependencies.py 中替换为 Qdrant 实现，此文件不改动。
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path

import yaml

from app.config import get_settings
from app.protocols import (
    ExampleRetriever,
    KnowledgeChunk,
    KnowledgeRetriever,
    SQLExample,
    SchemaRetriever,
    TableSchema,
)

logger = logging.getLogger(__name__)


def _knowledge_dir() -> Path:
    return get_settings().knowledge_dir


# ── 方言规则加载 ──────────────────────────────────────────────────────────────────

@lru_cache
def load_dialect_rules() -> dict:
    """加载所有方言规则 YAML，合并为一个 dict。结果缓存。"""
    rules_dir = _knowledge_dir() / "dialect_rules"
    result: dict = {"unsupported": [], "syntax": [], "functions": {"supported": [], "unsupported": []}}

    if not rules_dir.exists():
        logger.warning("dialect_rules 目录不存在: %s", rules_dir)
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
        """Phase 1: 返回指定 db_id 的完整 schema DDL（全量注入）。"""
        from sqlalchemy import select

        from app.models.connection import DbConnection

        result = await self._session.execute(
            select(DbConnection).where(DbConnection.id == db_id, DbConnection.is_active.is_(True))
        )
        conn = result.scalar_one_or_none()
        if not conn or not conn.schema_ddl:
            return []

        # Phase 1: 将整个 DDL 作为一个 TableSchema 返回
        return [TableSchema(table_name="__all__", ddl=conn.schema_ddl, description=f"{conn.name} 数据库 Schema")]


# 验证实现满足 Protocol
def _verify_protocol():
    pass  # DbSchemaRetriever 在实例化时才能验证（需要 session），此处跳过


# ── ExampleRetriever Phase 1 实现 ──────────────────────────────────────────────────

class FileExampleRetriever:
    """
    ExampleRetriever Phase 1 实现：从 JSONL 文件加载所有示例，返回前 top_k 条。
    Phase 3 升级：替换为 QdrantExampleRetriever（向量相似度检索）。
    """

    def __init__(self):
        self._examples: list[SQLExample] | None = None

    def _load(self) -> list[SQLExample]:
        if self._examples is not None:
            return self._examples

        examples_path = _knowledge_dir() / "examples" / "sql_examples.jsonl"
        self._examples = []

        if not examples_path.exists():
            logger.warning("sql_examples.jsonl 不存在: %s", examples_path)
            return self._examples

        with open(examples_path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    data = json.loads(line)
                    self._examples.append(
                        SQLExample(
                            question=data["question"],
                            sql=data["sql"],
                            tables=data.get("tables", []),
                            pattern=data.get("pattern", ""),
                            difficulty=data.get("difficulty", "medium"),
                        )
                    )
                except Exception as e:
                    logger.warning("解析示例行失败: %s | %s", e, line[:80])

        logger.info("加载 %d 条 SQL 示例", len(self._examples))
        return self._examples

    async def retrieve(self, query: str, top_k: int = 5) -> list[SQLExample]:
        """Phase 1: 返回前 top_k 条示例（不做相关性过滤）。"""
        examples = self._load()
        return examples[:top_k]


assert isinstance(FileExampleRetriever(), ExampleRetriever)


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
            if (
                any(kw.lower() in query_lower for kw in keywords)
                or any(word in question for word in query_lower.split() if len(word) > 1)
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
