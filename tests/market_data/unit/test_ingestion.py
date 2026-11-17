from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pandas as pd
import pytest

import app.market_data.ingestion as ingestion
from app.market_data.fetcher import FetchedPriceHistory
from app.market_data.ingestion import build_price_payloads, ingest_price_history


def _history() -> FetchedPriceHistory:
    index = pd.date_range("2026-01-04", periods=3, freq="D")
    frame = pd.DataFrame(
        {
            "Open": [9.0, 10.0, 11.0],
            "High": [11.0, 12.0, 13.0],
            "Low": [8.0, 9.0, 10.0],
            "Close": [10.0, 11.0, 12.0],
            "Adj Close": [5.0, 5.5, 6.0],
            "Volume": [100, 200, 300],
            "Dividends": [0.0, 0.25, 0.0],
            "Stock Splits": [0.0, 0.0, 0.0],
        },
        index=index,
    )
    return FetchedPriceHistory("COMI.CA", "yahoo_finance", frame)


def test_build_payloads_preserves_raw_and_calculates_adjusted_prices() -> None:
    payload = build_price_payloads(_history())[0]

    assert payload["date"] == date(2026, 1, 4)
    assert payload["raw_close"] == Decimal("10.0")
    assert payload["adj_open"] == Decimal("4.5")
    assert payload["adj_high"] == Decimal("5.5")
    assert payload["adj_low"] == Decimal("4.0")
    assert payload["adj_close"] == Decimal("5.0")
    assert payload["volume"] == 100
    assert payload["source"] == "yahoo_finance"


def test_build_payloads_rejects_fractional_volume() -> None:
    history = _history()
    history.prices["Volume"] = history.prices["Volume"].astype(float)
    history.prices.loc[history.prices.index[0], "Volume"] = 1.5

    with pytest.raises(ValueError, match="Volume"):
        build_price_payloads(history)


@pytest.mark.asyncio
async def test_ingestion_counts_inserted_updated_and_unchanged(monkeypatch) -> None:
    payloads = build_price_payloads(_history())
    unchanged_row = SimpleNamespace(**payloads[0])
    changed_row = SimpleNamespace(**{**payloads[1], "raw_close": Decimal("10.0")})
    existing = [unchanged_row, changed_row]
    written: list[dict[str, object]] = []

    async def fake_get_history(_session, ticker):
        assert ticker == "COMI.CA"
        return existing

    async def fake_upsert(_session, values):
        written.append(values)
        return SimpleNamespace(**values)

    monkeypatch.setattr(ingestion, "get_stock_price_history", fake_get_history)
    monkeypatch.setattr(ingestion, "upsert_stock_price", fake_upsert)

    report = await ingest_price_history(object(), _history())

    assert (report.inserted, report.updated, report.unchanged) == (1, 1, 1)
    assert report.changed_dates == (date(2026, 1, 5), date(2026, 1, 6))
    assert [row["date"] for row in written] == [date(2026, 1, 5), date(2026, 1, 6)]


@pytest.mark.asyncio
async def test_ingestion_empty_history_does_not_query_or_write(monkeypatch) -> None:
    async def unexpected(*_args, **_kwargs):
        raise AssertionError("database should not be queried for an empty result")

    monkeypatch.setattr(ingestion, "get_stock_price_history", unexpected)
    monkeypatch.setattr(ingestion, "upsert_stock_price", unexpected)
    empty = FetchedPriceHistory("COMI.CA", "yahoo_finance", pd.DataFrame())

    report = await ingest_price_history(object(), empty)

    assert (report.inserted, report.updated, report.unchanged) == (0, 0, 0)
    assert report.changed_dates == ()
