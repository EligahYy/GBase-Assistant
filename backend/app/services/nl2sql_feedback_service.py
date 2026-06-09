"""NL2SQL Feedback Service — manages the lifecycle of query examples."""

from __future__ import annotations

import logging
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.nl2sql_case import NL2SQLAttempt, NL2SQLCase

logger = logging.getLogger(__name__)


class NL2SQLFeedbackService:
    """Handles feedback collection, case lifecycle, and evaluation data management."""

    def __init__(self, session: AsyncSession):
        self._session = session

    async def record_attempt(
        self,
        conversation_id: str,
        question: str,
        sql: str | None = None,
        status: str = "pending",
        error_message: str | None = None,
        error_category: str | None = None,
        latency_ms: float | None = None,
        llm_calls: int = 0,
        query_ir_json: str | None = None,
    ) -> NL2SQLAttempt:
        """Record an NL2SQL execution attempt."""
        attempt = NL2SQLAttempt(
            conversation_id=conversation_id,
            question=question,
            sql=sql,
            status=status,
            error_message=error_message,
            error_category=error_category,
            latency_ms=latency_ms,
            llm_calls=llm_calls,
            query_ir_json=query_ir_json,
        )
        self._session.add(attempt)
        await self._session.commit()
        return attempt

    async def submit_feedback(
        self,
        conversation_id: str,
        question: str,
        sql: str,
        action: str,  # "accept" | "modify" | "reject"
        corrected_sql: str | None = None,
        note: str | None = None,
        semantic_model_id: str | None = None,
        query_ir_json: str | None = None,
    ) -> NL2SQLCase:
        """Submit user feedback on a query result."""
        case = NL2SQLCase(
            question=question,
            sql=corrected_sql or sql,
            semantic_model_id=semantic_model_id,
            conversation_id=conversation_id,
            query_ir_json=query_ir_json,
            status="pending",
            source="auto",
        )

        if action == "reject":
            case.status = "rejected"
            case.error_category = "user_rejected"
        elif action == "modify":
            case.status = "pending"  # Modified but not yet verified
            case.sql = corrected_sql or sql
        elif action == "accept":
            case.status = "pending"  # Accepted but not yet admin-verified

        self._session.add(case)
        await self._session.commit()
        await self._session.refresh(case)
        return case

    async def verify_case(self, case_id: str, reviewer: str) -> NL2SQLCase | None:
        """Admin verifies a case for inclusion in the trusted example set."""
        result = await self._session.execute(
            select(NL2SQLCase).where(NL2SQLCase.id == case_id)
        )
        case = result.scalar_one_or_none()
        if case:
            case.status = "verified"
            case.reviewed_by = reviewer
            case.reviewed_at = datetime.now(UTC)
            await self._session.commit()
            await self._session.refresh(case)
        return case

    async def reject_case(self, case_id: str, reviewer: str) -> NL2SQLCase | None:
        """Admin rejects a case."""
        result = await self._session.execute(
            select(NL2SQLCase).where(NL2SQLCase.id == case_id)
        )
        case = result.scalar_one_or_none()
        if case:
            case.status = "rejected"
            case.reviewed_by = reviewer
            case.reviewed_at = datetime.now(UTC)
            await self._session.commit()
            await self._session.refresh(case)
        return case

    async def get_verified_examples(
        self,
        semantic_model_id: str | None = None,
        schema_version: str | None = None,
        limit: int = 5,
    ) -> list[NL2SQLCase]:
        """Retrieve verified examples for few-shot prompting."""
        stmt = select(NL2SQLCase).where(NL2SQLCase.status == "verified")
        if semantic_model_id:
            stmt = stmt.where(NL2SQLCase.semantic_model_id == semantic_model_id)
        if schema_version:
            stmt = stmt.where(NL2SQLCase.schema_version == schema_version)
        stmt = stmt.order_by(NL2SQLCase.quality_score.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())

    async def list_cases(
        self,
        status: str | None = None,
        semantic_model_id: str | None = None,
        limit: int = 50,
    ) -> list[NL2SQLCase]:
        """List cases with optional filters."""
        stmt = select(NL2SQLCase)
        if status:
            stmt = stmt.where(NL2SQLCase.status == status)
        if semantic_model_id:
            stmt = stmt.where(NL2SQLCase.semantic_model_id == semantic_model_id)
        stmt = stmt.order_by(NL2SQLCase.created_at.desc()).limit(limit)
        result = await self._session.execute(stmt)
        return list(result.scalars().all())
