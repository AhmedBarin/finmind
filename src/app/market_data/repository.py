"""Database operations for daily market prices.

Functions accept an ``AsyncSession`` and leave transaction boundaries to the
caller so a scraper can persist a batch atomically.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Mapping

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.models import StockPrice

_REQUIRED_PRICE_FIELDS = {"ticker", "date", "source"}
_SYSTEM_PRICE_FIELDS = {"id", "created_at", "updated_at", "fetched_at"}
_PRICE_FIELDS = set(StockPrice.__table__.columns.keys()) - _SYSTEM_PRICE_FIELDS


def _ticker_key(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if not normalized:
        raise ValueError("ticker must not be empty")
    return normalized


def _price_payload(values: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(values)
    missing = _REQUIRED_PRICE_FIELDS - payload.keys()
    unknown = payload.keys() - _PRICE_FIELDS
    if missing:
        raise ValueError(f"missing required price fields: {sorted(missing)}")
    if unknown:
        raise ValueError(f"unknown or managed price fields: {sorted(unknown)}")
    payload["ticker"] = _ticker_key(str(payload["ticker"]))
    if not isinstance(payload["date"], date) or isinstance(
        payload["date"], datetime
    ):
        raise ValueError("date must be a datetime.date value")
    return payload


async def upsert_stock_price(
    session: AsyncSession,
    values: Mapping[str, Any],
) -> StockPrice:
    """Insert or update the row identified by ``(ticker, date)``.

    Provider values omitted from ``values`` are left unchanged on conflict.
    ``fetched_at`` and ``updated_at`` are refreshed on every upsert. The caller
    is responsible for committing or rolling back the session.
    """
    payload = _price_payload(values)
    statement = pg_insert(StockPrice).values(**payload)
    update_fields = set(payload) - {"ticker", "date"}
    updates = {field: getattr(statement.excluded, field) for field in update_fields}
    updates.update(fetched_at=func.now(), updated_at=func.now())
    statement = (
        statement.on_conflict_do_update(
            constraint="uq_stock_prices_ticker_date",
            set_=updates,
        )
        .returning(StockPrice)
        .execution_options(populate_existing=True)
    )
    result = await session.scalars(statement)
    return result.one()


async def get_stock_price_by_date(
    session: AsyncSession,
    ticker: str,
    price_date: date,
) -> StockPrice | None:
    statement = select(StockPrice).where(
        StockPrice.ticker == _ticker_key(ticker),
        StockPrice.date == price_date,
    )
    return await session.scalar(statement)


async def get_latest_stock_price(
    session: AsyncSession,
    ticker: str,
) -> StockPrice | None:
    statement = (
        select(StockPrice)
        .where(StockPrice.ticker == _ticker_key(ticker))
        .order_by(StockPrice.date.desc())
        .limit(1)
    )
    return await session.scalar(statement)


async def get_stock_price_history(
    session: AsyncSession,
    ticker: str,
    *,
    start_date: date | None = None,
    end_date: date | None = None,
    limit: int | None = None,
) -> list[StockPrice]:
    """Return chronological prices with inclusive date bounds.

    When ``limit`` is supplied it selects the most recent rows in the range.
    """
    if start_date is not None and end_date is not None and start_date > end_date:
        raise ValueError("start_date must be on or before end_date")
    if limit is not None and limit < 1:
        raise ValueError("limit must be a positive integer")

    statement = select(StockPrice).where(StockPrice.ticker == _ticker_key(ticker))
    if start_date is not None:
        statement = statement.where(StockPrice.date >= start_date)
    if end_date is not None:
        statement = statement.where(StockPrice.date <= end_date)
    statement = statement.order_by(
        StockPrice.date.desc() if limit is not None else StockPrice.date.asc()
    )
    if limit is not None:
        statement = statement.limit(limit)
    result = await session.scalars(statement)
    rows = list(result.all())
    return list(reversed(rows)) if limit is not None else rows
