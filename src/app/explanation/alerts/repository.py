"""Read-only loaders for alert explanations."""

from __future__ import annotations

from datetime import date, timedelta
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.monitoring.models.alert import Alert
from app.technical_analysis import repository as technical_repository
from app.technical_analysis.models import TechnicalSnapshot


async def get_alert_for_user(
    session: AsyncSession, alert_id: UUID, user_id: UUID
) -> Alert | None:
    """Return the alert only if ``user_id`` owns it (otherwise ``None``)."""
    return await session.scalar(
        select(Alert).where(Alert.id == alert_id, Alert.user_id == user_id)
    )


async def get_alert_snapshots(
    session: AsyncSession, ticker: str, on: date | None
) -> tuple[TechnicalSnapshot | None, TechnicalSnapshot | None]:
    """Return (snapshot on the alert's data date, the snapshot before it)."""
    if on is None:
        return None, None
    current = await technical_repository.get_snapshot_by_date(session, ticker, on)
    earlier = await technical_repository.get_snapshot_history(
        session, ticker, end_date=on - timedelta(days=1), limit=1
    )
    return current, earlier[0] if earlier else None
