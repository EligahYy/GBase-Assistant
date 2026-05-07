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
    path = Path(get_settings().knowledge_dir) / "docs" / "error_codes.json"
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
        results = await qdrant.search(
            collection_name=collection,
            query_vector=embeddings[0],
            limit=top_k,
        )
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
    - 否则优先 Qdrant 语义检索（mode=semantic）；
    - 不可用时回退文件关键词匹配（mode=keyword）。
    """
    entries = _load_error_codes()
    if not entries:
        raise HTTPException(status_code=503, detail="错误码知识库尚未就绪")

    # 1. 精确匹配
    exact = _exact_match(payload.query, entries)
    if exact:
        return ErrorCodeResponse(query=payload.query, mode="exact", results=[_to_item(e) for e in exact])

    # 2. 语义检索
    semantic = await _semantic_match(payload.query, payload.top_k)
    if semantic:
        return ErrorCodeResponse(
            query=payload.query,
            mode="semantic",
            results=[_to_item(e, score=s) for s, e in semantic if e.get("code")],
        )

    # 3. 关键词回退
    matched = _keyword_match(payload.query, entries, payload.top_k)
    if matched:
        return ErrorCodeResponse(query=payload.query, mode="keyword", results=[_to_item(e) for e in matched])

    return ErrorCodeResponse(query=payload.query, mode="empty", results=[])
