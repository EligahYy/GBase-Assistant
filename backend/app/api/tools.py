"""工具类 API：错误码查询等独立工具入口。"""

from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from app.config import get_settings

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/tools", tags=["tools"])


class ErrorCodeQuery(BaseModel):
    query: str = Field(..., min_length=1, max_length=200, description="错误码（如 1064、GBA-2001）或自然语言关键词")
    top_k: int = Field(5, ge=1, le=20)


class ErrorCodeItem(BaseModel):
    code: str
    category: str = ""
    description: str
    solution: str = ""
    keywords: list[str] = []
    score: float | None = None


class ErrorCodeResponse(BaseModel):
    query: str
    mode: Literal["exact", "semantic", "keyword", "empty"]
    results: list[ErrorCodeItem]


@lru_cache
def _load_error_codes() -> list[dict]:
    """从 knowledge/docs/error_codes.json 加载所有错误码（带缓存）。"""
    path = Path(get_settings().knowledge_dir) / "error_codes.json"
    if not path.exists():
        logger.warning("error_codes.json 不存在: %s", path)
        return []
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f) or []
    except Exception as e:
        logger.error("加载 error_codes.json 失败: %s", e)
        return []


def _to_item(entry: dict, score: float | None = None) -> ErrorCodeItem:
    return ErrorCodeItem(
        code=str(entry.get("code", "")),
        category=entry.get("category", ""),
        description=entry.get("description", ""),
        solution=entry.get("solution", ""),
        keywords=entry.get("keywords", []) or [],
        score=score,
    )


def _exact_match(query: str, entries: list[dict]) -> list[dict]:
    """精确匹配 code 字段（不区分大小写）。"""
    q = query.strip().upper()
    return [e for e in entries if str(e.get("code", "")).upper() == q]


def _keyword_match(query: str, entries: list[dict], top_k: int) -> list[dict]:
    """文件级关键词匹配：在 code/description/solution/keywords 中找命中。"""
    q = query.lower()
    tokens = [t for t in q.replace("，", ",").replace(" ", ",").split(",") if t]
    if not tokens:
        tokens = [q]

    scored: list[tuple[int, dict]] = []
    for entry in entries:
        haystack_parts = [
            str(entry.get("code", "")),
            entry.get("description", ""),
            entry.get("solution", ""),
            " ".join(entry.get("keywords", []) or []),
        ]
        haystack = " ".join(haystack_parts).lower()
        score = sum(1 for t in tokens if t in haystack)
        if score > 0:
            scored.append((score, entry))

    scored.sort(key=lambda x: x[0], reverse=True)
    return [e for _, e in scored[:top_k]]


async def _semantic_match(query: str, top_k: int) -> list[tuple[float, dict]]:
    """通过 Qdrant 做语义检索，返回 (score, entry) 对。Qdrant 不可用时返回空列表。"""
    from app.vector.client import is_qdrant_available

    if not is_qdrant_available():
        return []

    try:
        from app.vector.client import get_qdrant_manager
        from app.vector.embedder import get_embedder

        embedder = get_embedder()
        qdrant = get_qdrant_manager().client
        collection = get_settings().models_config.get("collections", {}).get("error_codes", "error_codes")

        embeddings = await embedder.embed([query])
        results = await qdrant.query_points(
            collection_name=collection,
            query=embeddings[0],
            limit=top_k,
        )
        results = results.points if results else []
        return [
            (
                float(r.score) if r.score is not None else 0.0,
                {
                    "code": (r.payload or {}).get("code", ""),
                    "category": (r.payload or {}).get("category", ""),
                    "description": (r.payload or {}).get("description", ""),
                    "solution": (r.payload or {}).get("solution", ""),
                    "keywords": (r.payload or {}).get("keywords", []) or [],
                },
            )
            for r in results
        ]
    except Exception as e:
        logger.warning("错误码语义检索失败，回退到关键词: %s", e)
        return []


@router.post("/error-code", response_model=ErrorCodeResponse)
async def query_error_code(payload: ErrorCodeQuery) -> ErrorCodeResponse:
    """
    错误码查询。
    - 若 query 精确匹配某个 code，返回该条目（mode=exact）；
    - 否则优先 Qdrant 语义检索 error_codes 集合（mode=semantic）；
    - 不可用时回退文件关键词匹配（mode=keyword）；
    - 所有模式下追加 knowledge 集合检索手册相关章节（manual_context）。
    """
    entries = _load_error_codes()
    if not entries:
        raise HTTPException(status_code=503, detail="错误码知识库尚未就绪")

    results: list[ErrorCodeItem] = []
    mode: Literal["exact", "semantic", "keyword", "empty"] = "empty"

    # 1. 精确匹配
    exact = _exact_match(payload.query, entries)
    if exact:
        results = [_to_item(e) for e in exact]
        mode = "exact"
    else:
        # 2. 语义检索
        semantic = await _semantic_match(payload.query, payload.top_k)
        if semantic:
            results = [_to_item(e, score=s) for s, e in semantic if e.get("code")]
            mode = "semantic"

        # 3. 关键词回退
        if not results:
            matched = _keyword_match(payload.query, entries, payload.top_k)
            if matched:
                results = [_to_item(e) for e in matched]
                mode = "keyword"
            else:
                mode = "empty"

    # 4. 非精确匹配时，追加 RAG 知识库手册内容作为参考
    if mode != "exact":
        manual_chunks = await _search_knowledge_for_error(payload.query, top_k=3)
        if manual_chunks:
            for chunk in manual_chunks:
                results.append(ErrorCodeItem(
                    code="手册参考",
                    category="manual",
                description=chunk.get("title", ""),
                solution=chunk.get("content", "")[:2000],
                keywords=[],
                score=chunk.get("score"),
            ))

    return ErrorCodeResponse(query=payload.query, mode=mode, results=results)


async def _search_knowledge_for_error(query: str, top_k: int = 3) -> list[dict]:
    """在 knowledge 集合中搜索与错误码/错误相关的手册章节。"""
    from app.vector.client import is_qdrant_available

    if not is_qdrant_available():
        return []

    try:
        from app.vector.client import get_qdrant_manager
        from app.vector.embedder import get_embedder

        embedder = get_embedder()
        qdrant = get_qdrant_manager().client
        # 增强查询语义
        enhanced_query = f"GBase 8a 错误码 {query} 错误排查 解决方案"
        embeddings = await embedder.embed([enhanced_query])

        # 同时查 knowledge 集合获取手册内容
        results = await qdrant.query_points(
            collection_name="knowledge",
            query=embeddings[0],
            limit=top_k,
            score_threshold=0.3,
        )
        results = results.points if results else []
        return [
            {
                "title": (r.payload or {}).get("title", ""),
                "content": (r.payload or {}).get("content", ""),
                "score": float(r.score) if r.score else 0.0,
            }
            for r in results
            if (r.payload or {}).get("content")
        ]
    except Exception as e:
        logger.debug("知识库错误码搜索跳过: %s", e)
        return []
