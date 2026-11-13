from __future__ import annotations

from datetime import date
from types import SimpleNamespace

import pytest

import app.market_data.jobs as jobs


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

    await jobs._recalculate_affected_snapshots(
        object(), "COMI.CA", date(2026, 1, 5)
    )

    assert recalculated == [
        ("COMI.CA", date(2026, 1, 6), date(2026, 1, 6)),
        ("COMI.CA", date(2026, 1, 8), date(2026, 1, 8)),
    ]


@pytest.mark.asyncio
async def test_job_rejects_unknown_period_before_fetching() -> None:
    with pytest.raises(ValueError, match="period"):
        await jobs.run_market_data_job(object(), ["COMI.CA"], period="5y")
