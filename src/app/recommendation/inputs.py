"""Read-only adapters for Recommendation Engine source data."""

from __future__ import annotations

from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.models import Company
from app.investor.repository import get_active_profile_payload
from app.technical_analysis.repository import get_latest_valid_snapshot
from app.technical_analysis.schemas import TechnicalSnapshotRead

from app.recommendation.schemas import RecommendationInputs


async def load_recommendation_inputs(
    session: AsyncSession,
    *,
    user_id: UUID,
    ticker: str,
) -> RecommendationInputs:
    """Load the active confirmed profile and latest valid snapshot, without writes.

    News is intentionally not read. The caller receives missing profile or
    snapshot as ``None`` so the decision layer can return a clear result.
    """
    normalized_ticker = ticker.strip().upper()
    if not normalized_ticker:
        raise ValueError("ticker must not be empty")

    profile = await get_active_profile_payload(session, user_id)
    snapshot_record = await get_latest_valid_snapshot(session, normalized_ticker)
    snapshot = (
        TechnicalSnapshotRead.model_validate(snapshot_record)
        if snapshot_record is not None
        else None
    )
    company_ticker = normalized_ticker.removesuffix(".CA")
    company = await session.scalar(
        select(Company).where(
            Company.exchange == "EGX",
            Company.ticker == company_ticker,
            Company.is_active.is_(True),
        )
    )
    liquidity_rank_pct = (
        snapshot.indicators.get("liquidity_rank_pct") if snapshot is not None else None
    )

    return RecommendationInputs(
        user_id=user_id,
        ticker=normalized_ticker,
        profile=profile,
        snapshot=snapshot,
        sector=company.sector if company is not None else None,
        liquidity_rank_pct=liquidity_rank_pct,
    )
