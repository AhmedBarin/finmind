from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pandas as pd
import pytest

import app.market_data.jobs as jobs
from app.market_data.fetcher import FetchedPriceHistory
from app.market_data.ingestion import IngestionReport


@pytest.mark.asyncio
async def test_recalculate_updates_existing_snapshots_from_first_change(monkeypatch) -> None:
    recalculated: list[tuple[str, date, date]] = []

    async def fake_latest(_session, ticker):
        assert ticker == "COMI.CA"
        return SimpleNamespace(date=date(2026, 1, 8))

    async def fake_history(_session, ticker, *, start_date, end_date):
        assert ticker == "COMI.CA"
        assert start_date == date(2026, 1, 5)
        assert end_date == date(2026, 1, 8)
        # Repository returns newest first; the job should recalculate chronologically.
        return [
            SimpleNamespace(date=date(2026, 1, 8)),
            SimpleNamespace(date=date(2026, 1, 6)),
        ]

    async def fake_calculate(_session, ticker, snapshot_date):
        recalculated.append((ticker, snapshot_date, snapshot_date))

    monkeypatch.setattr(jobs, "get_latest_stock_price", fake_latest)
    monkeypatch.setattr(jobs, "get_snapshot_history", fake_history)
    monkeypatch.setattr(jobs, "calculate_and_persist_snapshot", fake_calculate)

    dates = await jobs._recalculate_affected_snapshots(
        object(), "COMI.CA", date(2026, 1, 5)
    )

    assert dates == (date(2026, 1, 6), date(2026, 1, 8))
    assert recalculated == [
        ("COMI.CA", date(2026, 1, 6), date(2026, 1, 6)),
        ("COMI.CA", date(2026, 1, 8), date(2026, 1, 8)),
    ]


@pytest.mark.asyncio
async def test_job_rejects_unknown_period_before_fetching() -> None:
    with pytest.raises(ValueError, match="period"):
        await jobs.run_market_data_job(object(), ["COMI.CA"], period="5y")


@pytest.mark.asyncio
async def test_full_egx30_job_ranks_after_all_ticker_snapshots(monkeypatch) -> None:
    as_of_date = date(2026, 11, 16)
    tickers = ("AAA.CA", "BBB.CA")
    monkeypatch.setattr(jobs, "EGX30_TICKERS", tickers)
    ranked: list[date] = []

    class Context:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *_exc_info):
            return None

    class FakeSession:
        def begin(self):
            return Context()

    class FakeSessionFactory:
        def __call__(self):
            return ContextWithSession()

    class ContextWithSession(Context):
        async def __aenter__(self):
            return FakeSession()

    class FakeFetcher:
        async def fetch(self, ticker: str, *, period: str) -> FetchedPriceHistory:
            assert period == "1mo"
            return FetchedPriceHistory(
                ticker=ticker,
                source="test",
                prices=pd.DataFrame(),
            )

    async def fake_ingest(_session, history):
        return IngestionReport(
            ticker=history.ticker,
            source=history.source,
            inserted=1,
            updated=0,
            unchanged=0,
            changed_dates=(as_of_date,),
        )

    async def fake_recalculate(_session, ticker, _earliest_date):
        return (as_of_date,)

    async def fake_rank(_session, requested_date):
        ranked.append(requested_date)
        return SimpleNamespace(ranked_tickers=tickers, unavailable_tickers=())

    monkeypatch.setattr(jobs, "ingest_price_history", fake_ingest)
    monkeypatch.setattr(jobs, "_recalculate_affected_snapshots", fake_recalculate)
    monkeypatch.setattr(jobs, "rank_egx30_snapshots", fake_rank)

    results = await jobs.run_market_data_job(
        FakeSessionFactory(),
        tickers,
        period="1mo",
        fetcher=FakeFetcher(),
    )

    assert len(results) == 2
    assert ranked == [as_of_date]
