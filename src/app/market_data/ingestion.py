"""Idempotent ingestion of one provider's daily price history."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.fetcher import FetchedPriceHistory
from app.market_data.processor import normalize_ohlcv
from app.market_data.repository import get_stock_price_history, upsert_stock_price


_PRICE_FIELDS = (
    "raw_open",
    "raw_high",
    "raw_low",
    "raw_close",
    "adj_open",
    "adj_high",
    "adj_low",
    "adj_close",
    "volume",
    "dividends",
    "stock_splits",
    "source",
)
_PRICE_QUANTUM = Decimal("0.000001")


@dataclass(frozen=True)
class IngestionReport:
    ticker: str
    source: str
    inserted: int
    updated: int
    unchanged: int
    changed_dates: tuple[date, ...]


def _decimal_or_none(value: Any, field: str) -> Decimal | None:
    if pd.isna(value):
        return None
    try:
        converted = Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{field} must be numeric") from exc
    if not converted.is_finite():
        raise ValueError(f"{field} must be finite")
    return converted


def build_price_payloads(history: FetchedPriceHistory) -> list[dict[str, Any]]:
    """Convert fetched provider rows to validated StockPrice values."""
    frame = history.prices
    if frame.empty:
        return []
    if not isinstance(frame.index, pd.DatetimeIndex):
        raise ValueError("fetched price history must have a DatetimeIndex")
    if frame.index.has_duplicates:
        raise ValueError("fetched price history contains duplicate dates")

    processed = normalize_ohlcv(frame)
    payloads: list[dict[str, Any]] = []
    for price_date, row in processed.iterrows():
        if pd.isna(price_date):
            raise ValueError("fetched price history contains an invalid date")
        volume_decimal = _decimal_or_none(row["Volume"], "Volume")
        if volume_decimal is not None and volume_decimal < 0:
            raise ValueError("Volume must be a non-negative integer")
        if (
            volume_decimal is not None
            and volume_decimal != volume_decimal.to_integral_value()
        ):
            raise ValueError("Volume must be a non-negative integer")

        payload: dict[str, Any] = {
            "ticker": history.ticker,
            "date": pd.Timestamp(price_date).date(),
            "raw_open": _decimal_or_none(row["Open"], "Open"),
            "raw_high": _decimal_or_none(row["High"], "High"),
            "raw_low": _decimal_or_none(row["Low"], "Low"),
            "raw_close": _decimal_or_none(row["Close"], "Close"),
            "adj_open": _decimal_or_none(row["adj_open"], "adj_open"),
            "adj_high": _decimal_or_none(row["adj_high"], "adj_high"),
            "adj_low": _decimal_or_none(row["adj_low"], "adj_low"),
            "adj_close": _decimal_or_none(row["adj_close"], "adj_close"),
            "volume": int(volume_decimal) if volume_decimal is not None else None,
            "dividends": _decimal_or_none(
                row.get("Dividends", 0), "Dividends"
            ),
            "stock_splits": _decimal_or_none(
                row.get("Stock Splits", 0), "Stock Splits"
            ),
            "source": history.source,
        }
        payloads.append(payload)
    return payloads


def _same_value(field: str, stored: Any, incoming: Any) -> bool:
    if stored is None or incoming is None:
        return stored is None and incoming is None
    if field == "source":
        return stored == incoming
    if field == "volume":
        return int(stored) == int(incoming)
    try:
        stored_decimal = Decimal(str(stored)).quantize(_PRICE_QUANTUM)
        incoming_decimal = Decimal(str(incoming)).quantize(_PRICE_QUANTUM)
    except (InvalidOperation, ValueError):
        return False
    return stored_decimal == incoming_decimal


def _changed_fields(stored: Any, incoming: dict[str, Any]) -> set[str]:
    return {
        field
        for field in _PRICE_FIELDS
        if not _same_value(field, getattr(stored, field), incoming[field])
    }


async def ingest_price_history(
    session: AsyncSession,
    history: FetchedPriceHistory,
) -> IngestionReport:
    """Insert new dates, skip identical rows, and update changed rows.

    The caller owns transaction commit/rollback. Snapshot recalculation is
    intentionally left to the ingestion job, which can use changed_dates.
    """
    ticker = history.ticker.strip().upper()
    if not ticker:
        raise ValueError("ticker must not be empty")
    if not history.source.strip():
        raise ValueError("source must not be empty")

    payloads = build_price_payloads(history)
    if not payloads:
        return IngestionReport(ticker, history.source, 0, 0, 0, ())

    existing_rows = await get_stock_price_history(session, ticker)
    existing_by_date = {row.date: row for row in existing_rows}
    inserted = updated = unchanged = 0
    changed_dates: list[date] = []

    for payload in payloads:
        price_date = payload["date"]
        stored = existing_by_date.get(price_date)
        if stored is None:
            await upsert_stock_price(session, payload)
            inserted += 1
            changed_dates.append(price_date)
        elif _changed_fields(stored, payload):
            await upsert_stock_price(session, payload)
            updated += 1
            changed_dates.append(price_date)
        else:
            unchanged += 1

    return IngestionReport(
        ticker=ticker,
        source=history.source,
        inserted=inserted,
        updated=updated,
        unchanged=unchanged,
        changed_dates=tuple(sorted(changed_dates)),
    )
