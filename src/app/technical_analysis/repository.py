"""Database operations for reproducible technical snapshots."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.technical_analysis.models import TechnicalSnapshot

_REQUIRED_SNAPSHOT_FIELDS = {
    "ticker",
    "date",
    "config_version",
    "data_quality_status",
}
_SYSTEM_SNAPSHOT_FIELDS = {"id", "calculated_at"}
_SNAPSHOT_FIELDS = (
    set(TechnicalSnapshot.__table__.columns.keys()) - _SYSTEM_SNAPSHOT_FIELDS
)


def _ticker_key(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if not normalized:
        raise ValueError("ticker must not be empty")
    return normalized


def _snapshot_payload(values: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(values)
    missing = _REQUIRED_SNAPSHOT_FIELDS - payload.keys()
    unknown = payload.keys() - _SNAPSHOT_FIELDS
    if missing:
        raise ValueError(f"missing required snapshot fields: {sorted(missing)}")
    if unknown:
        raise ValueError(f"unknown or managed snapshot fields: {sorted(unknown)}")
    payload["ticker"] = _ticker_key(str(payload["ticker"]))
    if not isinstance(payload["date"], date) or isinstance(
        payload["date"], datetime
    ):
        raise ValueError("date must be a datetime.date value")
    return payload


async def upsert_technical_snapshot(
    session: AsyncSession,
    values: Mapping[str, Any],
) -> TechnicalSnapshot:
    """Insert/update a snapshot for ``(ticker, date, config_version)``.

    Reprocessing the same date with another configuration version creates a
    separate reproducible row. The caller owns the transaction boundary.
    """
    payload = _snapshot_payload(values)
    statement = pg_insert(TechnicalSnapshot).values(**payload)
    conflict_fields = {"ticker", "date", "config_version"}
    update_fields = set(payload) - conflict_fields
    updates = {field: getattr(statement.excluded, field) for field in update_fields}
    updates["calculated_at"] = statement.excluded.calculated_at
    statement = (
        statement.on_conflict_do_update(
            constraint="uq_technical_snapshots_ticker_date_config",
            set_=updates,
        )
        .returning(TechnicalSnapshot)
        .execution_options(populate_existing=True)
    )
    result = await session.scalars(statement)
    return result.one()


async def get_latest_snapshot(
    session: AsyncSession,
    ticker: str,
) -> TechnicalSnapshot | None:
    statement = (
        select(TechnicalSnapshot)
        .where(TechnicalSnapshot.ticker == _ticker_key(ticker))
        .order_by(
            TechnicalSnapshot.date.desc(),
            TechnicalSnapshot.calculated_at.desc(),
        )
        .limit(1)
    )
    return await session.scalar(statement)


async def get_latest_valid_snapshot(
    session: AsyncSession,
    ticker: str,
) -> TechnicalSnapshot | None:
    """Return the newest snapshot whose data-quality status is valid."""
    statement = (
        select(TechnicalSnapshot)
        .where(
            TechnicalSnapshot.ticker == _ticker_key(ticker),
            TechnicalSnapshot.data_quality_status == "valid",
        )
        .order_by(
            TechnicalSnapshot.date.desc(),
            TechnicalSnapshot.calculated_at.desc(),
        )
        .limit(1)
    )
    return await session.scalar(statement)


async def get_snapshot_by_date(
    session: AsyncSession,
    ticker: str,
    snapshot_date: date,
    *,
    config_version: str | None = None,
) -> TechnicalSnapshot | None:
    statement = select(TechnicalSnapshot).where(
        TechnicalSnapshot.ticker == _ticker_key(ticker),
        TechnicalSnapshot.date == snapshot_date,
    )
    if config_version is not None:
        statement = statement.where(
            TechnicalSnapshot.config_version == config_version
        )
    statement = statement.order_by(TechnicalSnapshot.calculated_at.desc()).limit(1)
    return await session.scalar(statement)


async def get_snapshot_history(
    session: AsyncSession,
    ticker: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int | None = None,
) -> list[TechnicalSnapshot]:
    """Return snapshots in descending date order, with inclusive date bounds."""
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    if limit is not None and limit < 1:
        raise ValueError("limit must be a positive integer")

    statement = select(TechnicalSnapshot).where(
        TechnicalSnapshot.ticker == _ticker_key(ticker)
    )
    if start_date is not None:
        statement = statement.where(TechnicalSnapshot.date >= start_date)
    if end_date is not None:
        statement = statement.where(TechnicalSnapshot.date <= end_date)
    statement = statement.order_by(
        TechnicalSnapshot.date.desc(), TechnicalSnapshot.calculated_at.desc()
    )
    if limit is not None:
        statement = statement.limit(limit)
    result = await session.scalars(statement)
    return list(result.all())


async def compare_snapshots(
    session: AsyncSession,
    ticker: str,
    first_date: date,
    second_date: date,
    *,
    config_version: str | None = None,
) -> tuple[TechnicalSnapshot | None, TechnicalSnapshot | None]:
    """Return snapshots for two dates in the caller's requested order."""
    first = await get_snapshot_by_date(
        session, ticker, first_date, config_version=config_version
    )
    second = await get_snapshot_by_date(
        session, ticker, second_date, config_version=config_version
    )
    return first, second
