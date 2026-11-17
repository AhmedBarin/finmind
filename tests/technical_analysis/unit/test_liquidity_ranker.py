from __future__ import annotations

from datetime import date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.technical_analysis.liquidity_ranker as liquidity_ranker
from app.technical_analysis.config import EGX30_TICKERS
from app.technical_analysis.liquidity_ranker import rank_egx30_snapshots, rank_liquidity_values


def test_configured_egx30_universe_has_30_unique_tickers() -> None:
    assert len(EGX30_TICKERS) == 30
    assert len(set(EGX30_TICKERS)) == 30
    assert "VLMR.CA" in EGX30_TICKERS


def test_percentile_rank_is_ascending_and_higher_means_more_liquid() -> None:
    ranks = rank_liquidity_values(
        {"LOW.CA": 10, "MID.CA": 20, "HIGH.CA": 30},
        universe_tickers=("LOW.CA", "MID.CA", "HIGH.CA"),
    )

    assert ranks == {
        "LOW.CA": pytest.approx(100 / 3),
        "MID.CA": pytest.approx(200 / 3),
        "HIGH.CA": pytest.approx(100),
    }


def test_equal_traded_values_receive_average_tie_rank() -> None:
    ranks = rank_liquidity_values(
        {"A.CA": 10, "B.CA": 20, "C.CA": 20, "D.CA": 40},
        universe_tickers=("A.CA", "B.CA", "C.CA", "D.CA"),
    )

    assert ranks == {
        "A.CA": pytest.approx(25),
        "B.CA": pytest.approx(62.5),
        "C.CA": pytest.approx(62.5),
        "D.CA": pytest.approx(100),
    }


def test_missing_invalid_and_out_of_universe_values_are_excluded() -> None:
    ranks = rank_liquidity_values(
        {
            "A.CA": 0,
            "B.CA": 100,
            "C.CA": None,
            "D.CA": float("nan"),
            "E.CA": -1,
            "OUTSIDE.CA": 500,
        },
        universe_tickers=("A.CA", "B.CA", "C.CA", "D.CA", "E.CA"),
    )

    assert ranks == {"A.CA": pytest.approx(50), "B.CA": pytest.approx(100)}


@pytest.mark.parametrize(
    "universe",
    [(), ("A.CA", "A.CA"), ("A.CA", " a.ca ")],
)
def test_invalid_universe_is_rejected(universe: tuple[str, ...]) -> None:
    with pytest.raises(ValueError, match="universe_tickers"):
        rank_liquidity_values({}, universe_tickers=universe)


@pytest.mark.asyncio
async def test_rank_pass_saves_reproducible_immutable_snapshot_variants(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    as_of_date = date(2026, 11, 16)
    snapshots = {
        "A.CA": _snapshot("A.CA", as_of_date, 100.0),
        "B.CA": _snapshot("B.CA", as_of_date, 200.0),
        # C has no valid snapshot and is recorded as unavailable.
        "C.CA": None,
    }
    saved_payloads: list[dict[str, object]] = []

    async def fake_get_snapshot(_session, ticker, requested_date):
        assert requested_date == as_of_date
        return snapshots[ticker]

    async def fake_save_snapshot(_session, values):
        payload = dict(values)
        saved_payloads.append(payload)
        saved = SimpleNamespace(
            **payload,
            id=uuid4(),
            calculated_at=datetime(2026, 11, 16, 16, 0),
        )
        snapshots[str(payload["ticker"])] = saved
        return saved

    monkeypatch.setattr(
        liquidity_ranker, "get_snapshot_by_date", fake_get_snapshot
    )
    monkeypatch.setattr(
        liquidity_ranker, "save_technical_snapshot", fake_save_snapshot
    )

    report = await rank_egx30_snapshots(
        object(),
        as_of_date,
        universe_tickers=("A.CA", "B.CA", "C.CA"),
        universe_version="test-v1",
    )
    first_hashes = {
        ticker: str(payload["input_hash"])
        for ticker, payload in {
            str(row["ticker"]): row for row in saved_payloads
        }.items()
    }

    await rank_egx30_snapshots(
        object(),
        as_of_date,
        universe_tickers=("A.CA", "B.CA", "C.CA"),
        universe_version="test-v1",
    )

    assert report.ranked_tickers == ("A.CA", "B.CA")
    assert report.unavailable_tickers == ("C.CA",)
    assert len(saved_payloads) == 4
    saved_by_ticker = {
        str(row["ticker"]): row for row in saved_payloads[:2]
    }
    assert saved_by_ticker["A.CA"]["indicators"]["liquidity_rank_pct"] == 50
    assert saved_by_ticker["B.CA"]["indicators"]["liquidity_rank_pct"] == 100
    assert saved_by_ticker["A.CA"]["input_hash"] != saved_by_ticker["B.CA"]["input_hash"]
    assert saved_by_ticker["A.CA"]["input_data"]["liquidity_rank"]["universe_version"] == "test-v1"
    assert saved_by_ticker["A.CA"]["input_data"]["liquidity_rank"]["unavailable_tickers"] == ["C.CA"]
    assert saved_by_ticker["A.CA"]["input_data"]["source_snapshot_input_hash"] == "A.CA:base"
    second_hashes = {
        str(row["ticker"]): str(row["input_hash"])
        for row in saved_payloads[2:]
    }
    assert second_hashes == first_hashes


def _snapshot(ticker: str, as_of_date: date, traded_value: float) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid4(),
        ticker=ticker,
        date=as_of_date,
        calculated_at=datetime(2026, 11, 16, 15, 30),
        config_version="technical-v1",
        input_hash=f"{ticker}:base",
        data_quality_status="valid",
        rsi=52.0,
        sma_20=10.0,
        sma_50=9.5,
        atr=0.2,
        setup_score=60.0,
        regime="trending",
        risk_label="medium",
        input_data={"source_window": [{"Close": 10.0}]},
        indicators={"avg_traded_value_20d": traded_value, "liquidity_rank_pct": None},
        scores={"family_scores": {}},
        quality_flags=[],
    )
