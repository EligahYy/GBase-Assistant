"""SQL 反馈闭环：将用户反馈 enrich 为新的 few-shot example。"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.message import Message
from app.models.sql_feedback import SQLFeedback
from app.protocols import SQLExample
from app.vector.client import is_qdrant_available

logger = logging.getLogger(__name__)

EXAMPLES_PATH = Path(__file__).parent.parent.parent / "knowledge" / "examples" / "sql_examples.jsonl"


def _compute_hash(question: str, sql: str) -> str:
    """计算 question + sql 的哈希，用于去重。"""
    return hashlib.sha256(f"{question.strip()}|{sql.strip()}".encode()).hexdigest()[:16]


def _extract_tables_from_sql(sql: str) -> list[str]:
    """从 SQL 中提取表名（简单正则）。"""
    tables = set()
    # FROM / JOIN table_name
    for m in re.finditer(r"\b(FROM|JOIN)\s+`?(\w+)`?", sql, re.IGNORECASE):
        tables.add(m.group(2))
    return sorted(tables)


def _detect_pattern(sql: str) -> str:
    """自动检测 SQL 模式。"""
    s = sql.upper()
    if "ROW_NUMBER()" in s or "RANK()" in s or "DENSE_RANK()" in s:
        return "window_function"
    if "GROUP BY" in s and ("COUNT(" in s or "SUM(" in s or "AVG(" in s or "MAX(" in s or "MIN(" in s):
        return "aggregation"
    if "JOIN" in s:
        return "join"
    if "WITH " in s:
        return "cte"
    if "CREATE TABLE" in s:
        return "ddl"
    if "INSERT " in s:
        return "insert"
    return "select"


def _load_existing_hashes() -> set[str]:
    """加载 JSONL 中已有 example 的哈希集合。"""
    hashes = set()
    if not EXAMPLES_PATH.exists():
        return hashes
    with open(EXAMPLES_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                ex = json.loads(line)
                h = _compute_hash(ex.get("question", ""), ex.get("sql", ""))
                hashes.add(h)
            except json.JSONDecodeError:
                continue
    return hashes


def _append_example(example: SQLExample) -> None:
    """追加单个 example 到 JSONL 文件。"""
    EXAMPLES_PATH.parent.mkdir(parents=True, exist_ok=True)
    record = {
        "question": example.question,
        "sql": example.sql,
        "tables": example.tables,
        "pattern": example.pattern,
        "difficulty": example.difficulty,
    }
    with open(EXAMPLES_PATH, "a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    logger.info("Feedback enricher: 追加 example | question=%.40s", example.question)


async def _find_user_question(db: AsyncSession, message_id: str) -> str | None:
    """通过 message_id 找到对应的用户原始问题。"""
    # 获取消息所属的 conversation
    result = await db.execute(
        select(Message).where(Message.id == message_id)
    )
    msg = result.scalar_one_or_none()
    if not msg:
        return None

    # 加载 conversation 的所有 messages（利用 relationship 的 lazy loading 或 eager load）
    conversation = msg.conversation
    if not conversation or not conversation.messages:
        return None

    # 按时间排序，找到目标消息的前一个 user 消息
    sorted_msgs = sorted(conversation.messages, key=lambda m: m.created_at)
    target_idx = None
    for i, m in enumerate(sorted_msgs):
        if m.id == message_id:
            target_idx = i
            break

    if target_idx is None:
        return None

    # 向前查找最近的 user 消息
    for i in range(target_idx - 1, -1, -1):
        if sorted_msgs[i].role == "user":
            return sorted_msgs[i].content.strip()

    return None


async def enrich_feedback_examples(
    db: AsyncSession,
    max_items: int = 50,
) -> dict[str, int]:
    """将未 enrich 的 feedback 转为 few-shot examples。

    Returns:
        {"added": N, "skipped": N, "failed": N}
    """
    # 1. 查询未 enrich 的 feedback（accepted / modified）
    result = await db.execute(
        select(SQLFeedback)
        .where(SQLFeedback.enriched_at.is_(None))  # noqa: E712
        .where(SQLFeedback.action.in_(["accepted", "modified"]))
        .order_by(SQLFeedback.created_at.asc())
        .limit(max_items)
    )
    feedbacks = result.scalars().all()

    if not feedbacks:
        return {"added": 0, "skipped": 0, "failed": 0}

    existing_hashes = _load_existing_hashes()
    added = 0
    skipped = 0
    failed = 0

    for fb in feedbacks:
        try:
            # 确定使用的 SQL
            sql = fb.modified_sql if fb.action == "modified" and fb.modified_sql else fb.original_sql
            if not sql:
                skipped += 1
                fb.enriched_at = datetime.now(UTC)
                continue

            # 获取用户问题
            question = await _find_user_question(db, fb.message_id)
            if not question:
                logger.warning("Feedback enricher: 无法找到 message_id=%s 的用户问题", fb.message_id)
                failed += 1
                continue

            # 去重检查
            h = _compute_hash(question, sql)
            if h in existing_hashes:
                skipped += 1
                fb.enriched_at = datetime.now(UTC)
                continue

            # 生成 example
            example = SQLExample(
                question=question,
                sql=sql,
                tables=_extract_tables_from_sql(sql),
                pattern=_detect_pattern(sql),
                difficulty="medium",
            )

            # 追加到 JSONL
            _append_example(example)
            existing_hashes.add(h)
            added += 1
            fb.enriched_at = datetime.now(UTC)

        except Exception as e:
            logger.warning("Feedback enricher: 处理 feedback %s 失败: %s", fb.id, e)
            failed += 1

    await db.commit()

    # 如果有新增，触发 Qdrant re-ingest（后台执行）
    if added > 0 and is_qdrant_available():
        try:
            from app.vector.embedder import get_embedder
            from app.vector.ingest import ingest_sql_examples

            embedder = get_embedder()
            count = await ingest_sql_examples(embedder, force=True)
            logger.info("Feedback enricher: Qdrant re-ingest 完成，%d 条", count)
        except Exception as e:
            logger.warning("Feedback enricher: Qdrant re-ingest 失败: %s", e)

    return {"added": added, "skipped": skipped, "failed": failed}
