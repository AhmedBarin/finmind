"""Persistence and read queries for recommendation audit records."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.recommendation.models import RecommendationLog
from app.recommendation.schemas import RecommendationResult


async def save_recommendation_log(
    session: AsyncSession,
    *,
    user_id: UUID,
    result: RecommendationResult,
) -> RecommendationLog:
    """Persist one result; transaction commit/rollback belongs to the caller."""
    row = RecommendationLog(
        user_id=user_id,
        ticker=result.ticker,
        trading_date=result.trading_date,
        snapshot_id=result.snapshot_id,
        config_version=result.config_version,
        decision=result.decision.value,
        blockers=list(result.reasons),
        confidence=result.confidence.value,
    )
    session.add(row)
    await session.flush()
    return row


async def get_recommendation_history(
    session: AsyncSession,
    *,
    user_id: UUID,
    ticker: str | None = None,
    limit: int = 50,
) -> list[RecommendationLog]:
    """Read a user's recent recommendation log rows, optionally by ticker."""
    if limit < 1 or limit > 500:
        raise ValueError("limit must be between 1 and 500")

    statement = select(RecommendationLog).where(
        RecommendationLog.user_id == user_id
    )
    if ticker is not None:
        normalized_ticker = ticker.strip().upper()
        if not normalized_ticker:
            raise ValueError("ticker must not be empty")
        statement = statement.where(RecommendationLog.ticker == normalized_ticker)
    statement = statement.order_by(
        RecommendationLog.created_at.desc(), RecommendationLog.id.desc()
    ).limit(limit)
    result = await session.scalars(statement)
    return list(result.all())
