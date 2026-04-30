"""数据向量化入库脚本：FAQ / SQL 示例 / Schema / 错误码。"""

from __future__ import annotations

import hashlib
import json
import logging
from pathlib import Path

from app.config import get_settings
from app.knowledge.loader import _knowledge_dir
from app.protocols import Embedder
from app.vector.client import get_qdrant_manager

logger = logging.getLogger(__name__)

INDEX_STATE_FILE = Path("data/.vector_index_state.json")


def _get_index_state() -> dict:
    if INDEX_STATE_FILE.exists():
        with open(INDEX_STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_index_state(state: dict) -> None:
    INDEX_STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(INDEX_STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=2)


def _file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()[:16]


async def _embed_in_batches(embedder: Embedder, texts: list[str], batch_size: int = 10) -> list[list[float]]:
    """分批 embedding（兼容阿里云 batch size <= 10 限制）。"""
    all_embeddings: list[list[float]] = []
    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]
        embeddings = await embedder.embed(batch)
        all_embeddings.extend(embeddings)
    return all_embeddings


async def ingest_faq(embedder: Embedder, force: bool = False) -> int:
    """将 FAQ 向量化入库。返回入库条数。"""
    faq_path = _knowledge_dir() / "docs" / "faq.json"
    if not faq_path.exists():
        logger.warning("FAQ 文件不存在: %s", faq_path)
        return 0

    state = _get_index_state()
    current_hash = _file_hash(faq_path)
    if not force and state.get("faq_hash") == current_hash:
        logger.info("FAQ 未变更，跳过索引")
        return 0

    with open(faq_path, encoding="utf-8") as f:
        faq = json.load(f) or []

    qdrant = get_qdrant_manager().client
    collection = get_settings().models_config.get("collections", {}).get("knowledge", "knowledge")

    texts = [f"问题：{item['question']}\n答案：{item['answer']}" for item in faq]
    embeddings = await _embed_in_batches(embedder, texts)

    points = []
    for i, item in enumerate(faq):
        points.append(
            {
                "id": i,
                "vector": embeddings[i],
                "payload": {
                    "source": f"FAQ - {item.get('category', '通用')}",
                    "category": item.get("category", ""),
                    "content": f"问题：{item['question']}\n\n答案：{item['answer']}",
                },
            }
        )

    await qdrant.upsert(collection_name=collection, points=points, wait=True)

    state["faq_hash"] = current_hash
    _save_index_state(state)
    logger.info("FAQ 索引完成：%d 条", len(faq))
    return len(faq)


async def ingest_sql_examples(embedder: Embedder, force: bool = False) -> int:
    """将 SQL 示例向量化入库。返回入库条数。"""
    examples_path = _knowledge_dir() / "examples" / "sql_examples.jsonl"
    if not examples_path.exists():
        logger.warning("SQL 示例文件不存在: %s", examples_path)
        return 0

    state = _get_index_state()
    current_hash = _file_hash(examples_path)
    if not force and state.get("examples_hash") == current_hash:
        logger.info("SQL 示例未变更，跳过索引")
        return 0

    examples = []
    with open(examples_path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            examples.append(json.loads(line))

    qdrant = get_qdrant_manager().client
    collection = get_settings().models_config.get("collections", {}).get("sql_examples", "sql_examples")

    texts = [f"问题：{ex['question']}\nSQL：{ex['sql']}" for ex in examples]
    embeddings = await _embed_in_batches(embedder, texts)

    points = []
    for i, ex in enumerate(examples):
        points.append(
            {
                "id": i,
                "vector": embeddings[i],
                "payload": {
                    "question": ex["question"],
                    "sql": ex["sql"],
                    "tables": ex.get("tables", []),
                    "pattern": ex.get("pattern", ""),
                    "difficulty": ex.get("difficulty", "medium"),
                },
            }
        )

    await qdrant.upsert(collection_name=collection, points=points, wait=True)

    state["examples_hash"] = current_hash
    _save_index_state(state)
    logger.info("SQL 示例索引完成：%d 条", len(examples))
    return len(examples)


async def ingest_error_codes(embedder: Embedder, force: bool = False) -> int:
    """将错误码知识库向量化入库。返回入库条数。"""
    error_path = _knowledge_dir() / "docs" / "error_codes.json"
    if not error_path.exists():
        logger.info("错误码文件不存在，跳过: %s", error_path)
        return 0

    state = _get_index_state()
    current_hash = _file_hash(error_path)
    if not force and state.get("error_codes_hash") == current_hash:
        logger.info("错误码未变更，跳过索引")
        return 0

    with open(error_path, encoding="utf-8") as f:
        errors = json.load(f) or []

    qdrant = get_qdrant_manager().client
    collection = get_settings().models_config.get("collections", {}).get("error_codes", "error_codes")

    texts = [
        f"错误码：{item['code']}\n描述：{item['description']}\n解决方案：{item.get('solution', '')}" for item in errors
    ]
    embeddings = await _embed_in_batches(embedder, texts)

    points = []
    for i, item in enumerate(errors):
        points.append(
            {
                "id": i,
                "vector": embeddings[i],
                "payload": {
                    "code": item["code"],
                    "description": item["description"],
                    "solution": item.get("solution", ""),
                },
            }
        )

    await qdrant.upsert(collection_name=collection, points=points, wait=True)

    state["error_codes_hash"] = current_hash
    _save_index_state(state)
    logger.info("错误码索引完成：%d 条", len(errors))
    return len(errors)


async def ingest_schemas(
    embedder: Embedder,
    db_id: str,
    schemas: list[dict],
    force: bool = False,
) -> int:
    """将某个连接的 Schema 表结构向量化入库。返回入库条数。

    schemas: 每个元素为 {"table_name": str, "ddl": str, "columns": list[str], "description": str}
    """
    if not schemas:
        return 0

    state = _get_index_state()
    # 用 schemas 内容计算 hash
    content_hash = hashlib.sha256(json.dumps(schemas, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[
        :16
    ]
    state_key = f"schema_hash_{db_id}"
    if not force and state.get(state_key) == content_hash:
        logger.info("Schema %s 未变更，跳过索引", db_id)
        return 0

    qdrant = get_qdrant_manager().client
    collection = get_settings().models_config.get("collections", {}).get("schemas", "schemas")

    texts = [
        f"表名：{s.get('table_name', '')}\nDDL：{s.get('ddl', '')}\n描述：{s.get('description', '')}" for s in schemas
    ]
    embeddings = await _embed_in_batches(embedder, texts)

    points = []
    for i, s in enumerate(schemas):
        points.append(
            {
                "id": hashlib.sha256(f"{db_id}:{s.get('table_name', '')}".encode()).hexdigest()[:16],
                "vector": embeddings[i],
                "payload": {
                    "db_id": db_id,
                    "table_name": s.get("table_name", ""),
                    "ddl": s.get("ddl", ""),
                    "description": s.get("description", ""),
                    "columns": s.get("columns", []),
                },
            }
        )

    # 先删除该 db_id 下的旧数据，再插入新数据
    try:
        from qdrant_client.models import FieldCondition, Filter, MatchValue

        await qdrant.delete(
            collection_name=collection,
            points_selector=Filter(must=[FieldCondition(key="db_id", match=MatchValue(value=db_id))]),
        )
    except Exception as e:
        logger.warning("删除旧 schema 索引失败（可能 collection 不存在）: %s", e)

    await qdrant.upsert(collection_name=collection, points=points, wait=True)

    state[state_key] = content_hash
    _save_index_state(state)
    logger.info("Schema 索引完成：db_id=%s, %d 个表", db_id, len(schemas))
    return len(schemas)


async def sync_all_to_qdrant(embedder: Embedder, force: bool = False) -> dict:
    """一键同步所有知识库到 Qdrant。返回各 collection 入库条数。"""
    await get_qdrant_manager().ensure_collections(dimension=embedder.dimension)
    results = {}
    results["faq"] = await ingest_faq(embedder, force=force)
    results["sql_examples"] = await ingest_sql_examples(embedder, force=force)
    results["error_codes"] = await ingest_error_codes(embedder, force=force)
    logger.info("全量索引完成: %s", results)
    return results
