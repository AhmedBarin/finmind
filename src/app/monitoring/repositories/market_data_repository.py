"""Market-data repository – read-only adapter.

The monitoring service needs the latest price and technical-signal data
for each ticker it evaluates.  This module provides thin async helpers
that will eventually read from TM3 tables.  Until those tables exist,
callers should treat ``None`` returns as "data unavailable" and let the
freshness validator handle skipping.
"""

from __future__ import annotations

from app.monitoring.schemas.market_data import MarketDataPoint, TechnicalSignals


async def get_latest_market_data(
    ticker: str,
) -> MarketDataPoint | None:
    """Return the most recent daily OHLCV row for *ticker*.

    .. note::
        Placeholder – will query TM3 ``daily_prices`` (or equivalent)
        once the table is available.
    """
    # TODO(OD-02): wire up to TM3 market-data tables
    return None


async def get_latest_signals(
    ticker: str,
) -> TechnicalSignals | None:
    """Return the most recent technical-signal row for *ticker*.

    .. note::
        Placeholder – will query TM3 ``technical_indicators`` (or
        equivalent) and map columns to the ``TechnicalSignals`` contract
        (``rsi14 → rsi``, ``sma20 → sma_20``, etc.).
    """
    # TODO(OD-02): wire up to TM3 technical-signals tables
    return None
