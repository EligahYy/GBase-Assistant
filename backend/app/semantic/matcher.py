"""Hybrid semantic matching for governed NL2SQL assets.

The matcher combines deterministic lexical evidence with optional embeddings.
It never invents assets: callers pass the governed candidates that may be
returned.
"""

from __future__ import annotations

import logging
import math
import re
from dataclasses import dataclass, field
from typing import Any, Protocol

logger = logging.getLogger(__name__)

_QUERY_NOISE = re.compile(
    r"(请问|请帮我|帮我|查询|查一下|查下|查看|统计|分析|显示|列出|获取|想看|我要看|"
    r"全部|所有|一下|的|情况|数据)"
)
_TIME_EXPRESSIONS = re.compile(r"\d{2,4}年|全年|整年|上半年|下半年|\d{1,2}月|今年|去年|本月|上月|最近\d+[天周月年]")


class Embedder(Protocol):
    async def embed(self, texts: list[str]) -> list[list[float]]: ...


@dataclass
class SemanticMatch:
    asset: Any
    score: float
    evidence: list[str] = field(default_factory=list)
    lexical_score: float = 0.0
    embedding_score: float = 0.0


@dataclass
class MatchResult:
    matches: list[SemanticMatch] = field(default_factory=list)
    candidates: list[SemanticMatch] = field(default_factory=list)
    ambiguous: bool = False
    multi_intent: bool = False


class HybridSemanticMatcher:
    """Rank governed semantic assets using lexical and embedding evidence."""

    def __init__(
        self,
        embedder: Embedder | None = None,
        *,
        min_score: float = 0.46,
        ambiguity_margin: float = 0.06,
        max_results: int = 5,
        max_embedding_assets: int = 100,
    ) -> None:
        self._embedder = embedder
        self._min_score = min_score
        self._ambiguity_margin = ambiguity_margin
        self._max_results = max_results
        self._max_embedding_assets = max_embedding_assets
        self._embedding_cache: dict[str, list[float]] = {}

    async def match(
        self,
        question: str,
        assets: list[Any],
        *,
        asset_type: str,
        include_description: bool = True,
        use_embeddings: bool = True,
    ) -> MatchResult:
        if not question.strip() or not assets:
            return MatchResult()

        query = _normalize_query(question)
        rows = [
            self._lexical_match(
                query,
                asset,
                asset_type=asset_type,
                include_description=include_description,
            )
            for asset in assets
        ]
        if use_embeddings:
            await self._add_embedding_scores(question, rows, asset_type, include_description)

        accepted = []
        for row in rows:
            # Exact/alias evidence remains authoritative. Embeddings improve
            # recall but cannot independently produce a high-confidence match.
            if row.lexical_score >= 0.9:
                row.score = row.lexical_score
            elif row.embedding_score:
                row.score = 0.58 * row.embedding_score + 0.42 * row.lexical_score
            else:
                row.score = row.lexical_score
            if row.score >= self._min_score:
                accepted.append(row)

        accepted.sort(key=lambda item: item.score, reverse=True)
        rows.sort(key=lambda item: item.score, reverse=True)
        candidates = rows[: self._max_results]
        ranked = accepted[: self._max_results]
        multi_intent = bool(
            re.search(r"和|及|与|、|以及|分别|同时", question)
            and len([row for row in ranked if row.lexical_score >= 0.75]) > 1
        )
        ambiguity_margin = self._ambiguity_margin
        if len(_normalize_query(question)) <= 2:
            ambiguity_margin = max(ambiguity_margin, 0.25)
        ambiguous = (
            len(ranked) > 1
            and not multi_intent
            and ranked[0].score < 0.9
            and ranked[0].score - ranked[1].score < ambiguity_margin
        )
        return MatchResult(
            matches=ranked,
            candidates=candidates,
            ambiguous=ambiguous,
            multi_intent=multi_intent,
        )

    def _lexical_match(
        self,
        query: str,
        asset: Any,
        *,
        asset_type: str,
        include_description: bool,
    ) -> SemanticMatch:
        terms = _asset_terms(asset)
        best = 0.0
        evidence: list[str] = []
        for index, term in enumerate(terms):
            normalized = _normalize(term)
            if not normalized:
                continue
            if normalized == query:
                score = 1.0 if index == 0 else 0.97
                evidence.append(f"{'名称' if index == 0 else '别名'}完全匹配:{term}")
            elif normalized in query:
                coverage = len(normalized) / max(len(query), 1)
                score = min(0.96 if index == 0 else 0.93, 0.72 + 0.24 * coverage)
                evidence.append(f"{'名称' if index == 0 else '别名'}命中:{term}")
            else:
                score = _char_similarity(query, normalized)
                if score >= 0.35:
                    evidence.append(f"字符语义相似:{term}={score:.2f}")
            best = max(best, score)

        if include_description:
            description = _asset_description(asset, asset_type)
            desc_score = _char_similarity(query, _normalize(description))
            if desc_score >= 0.4:
                evidence.append(f"描述相似={desc_score:.2f}")
                best = max(best, desc_score * 0.86)

        return SemanticMatch(asset=asset, score=best, lexical_score=best, evidence=evidence)

    async def _add_embedding_scores(
        self,
        question: str,
        rows: list[SemanticMatch],
        asset_type: str,
        include_description: bool,
    ) -> None:
        if self._embedder is None or not rows:
            return
        selected_rows = sorted(rows, key=lambda row: row.lexical_score, reverse=True)[: self._max_embedding_assets]
        asset_texts = [_asset_embedding_text(row.asset, asset_type, include_description) for row in selected_rows]
        missing_texts = list(dict.fromkeys(text for text in asset_texts if text not in self._embedding_cache))
        try:
            vectors = await self._embedder.embed([question, *missing_texts])
            if len(vectors) != len(missing_texts) + 1:
                return
            query_vector = vectors[0]
            self._embedding_cache.update(zip(missing_texts, vectors[1:], strict=False))
            for row, text in zip(selected_rows, asset_texts, strict=False):
                vector = self._embedding_cache.get(text, [])
                cosine = _cosine_similarity(query_vector, vector)
                row.embedding_score = max(0.0, min(1.0, (cosine + 1.0) / 2.0))
                if row.embedding_score >= 0.65:
                    row.evidence.append(f"向量相似={row.embedding_score:.2f}")
        except Exception as exc:
            logger.warning("Semantic embedding match failed, using lexical fallback: %s", exc)


def _normalize_query(text: str) -> str:
    normalized = _normalize(text)
    normalized = _QUERY_NOISE.sub("", normalized)
    normalized = _TIME_EXPRESSIONS.sub("", normalized)
    return normalized or _normalize(text)


def _normalize(text: str) -> str:
    return re.sub(r"[\W_]+", "", str(text or "").lower())


def _asset_terms(asset: Any) -> list[str]:
    name = str(getattr(asset, "name", "") or getattr(asset, "display_value", ""))
    aliases = list(getattr(asset, "synonyms", None) or getattr(asset, "aliases", None) or [])
    return [name, *[str(alias) for alias in aliases if alias]]


def _asset_description(asset: Any, asset_type: str) -> str:
    parts = [str(getattr(asset, "description", "") or "")]
    if asset_type == "metric":
        parts.extend(
            [
                str(getattr(asset, "expression", "") or ""),
                " ".join(getattr(asset, "source_tables", None) or []),
            ]
        )
    elif asset_type == "dimension":
        parts.append(str(getattr(asset, "column_ref", "") or ""))
    elif asset_type == "member":
        parts.append(str(getattr(asset, "raw_value", "") or ""))
    return " ".join(part for part in parts if part)


def _asset_embedding_text(asset: Any, asset_type: str, include_description: bool) -> str:
    terms = "、".join(_asset_terms(asset))
    description = _asset_description(asset, asset_type) if include_description else ""
    return f"类型:{asset_type}; 名称与别名:{terms}; 定义:{description}"


def _char_similarity(left: str, right: str) -> float:
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    left_grams = _ngrams(left)
    right_grams = _ngrams(right)
    if not left_grams or not right_grams:
        return 0.0
    dice = 2 * len(left_grams & right_grams) / (len(left_grams) + len(right_grams))
    containment = len(left_grams & right_grams) / min(len(left_grams), len(right_grams))
    return 0.65 * dice + 0.35 * containment


def _ngrams(text: str) -> set[str]:
    if len(text) <= 2:
        return {text}
    return {text[index : index + 2] for index in range(len(text) - 1)}


def _cosine_similarity(left: list[float], right: list[float]) -> float:
    if not left or not right or len(left) != len(right):
        return 0.0
    dot = sum(a * b for a, b in zip(left, right, strict=False))
    left_norm = math.sqrt(sum(value * value for value in left))
    right_norm = math.sqrt(sum(value * value for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return dot / (left_norm * right_norm)
