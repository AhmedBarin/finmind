from datetime import date
from uuid import uuid4

import pytest
import pytest_asyncio

from app.db.session import SessionLocal, engine
from app.technical_analysis.repository import (
    compare_snapshots,
    get_latest_snapshot,
    get_latest_valid_snapshot,
    get_snapshot_by_date,
    get_snapshot_history,
    save_technical_snapshot,
)


@pytest_asyncio.fixture
async def db_session():
    try:
        async with SessionLocal() as session:
            transaction = await session.begin()
            try:
                yield session
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


def _snapshot_values(
    ticker: str,
    snapshot_date: date,
    *,
    status: str = "valid",
    score: float = 60.0,
    input_hash: str = "a" * 64,
) -> dict:
    return {
        "ticker": ticker,
        "date": snapshot_date,
        "config_version": "test-v1",
        "input_hash": input_hash,
        "data_quality_status": status,
        "rsi": 55.0,
        "sma_20": 10.5,
        "sma_50": 10.0,
        "atr": 0.8,
        "setup_score": score,
        "regime": "trending",
        "risk_label": "medium",
        "input_data": {"close": 11.0},
        "indicators": {"rsi14": 55.0},
        "scores": {"setup_score": score},
        "quality_flags": [],
    }


@pytest.mark.asyncio
async def test_snapshot_save_reads_history_and_comparison(db_session) -> None:
    ticker = f"T{uuid4().hex[:10]}".upper()
    first_date = date(2025, 2, 3)
    second_date = date(2025, 2, 4)

    first = await save_technical_snapshot(
        db_session, _snapshot_values(ticker, first_date, score=61.0)
    )
    same_inputs = await save_technical_snapshot(
        db_session,
        _snapshot_values(ticker, first_date, score=61.0),
    )
    corrected_inputs = await save_technical_snapshot(
        db_session,
        _snapshot_values(ticker, first_date, score=62.0, input_hash="b" * 64),
    )
    await save_technical_snapshot(
        db_session,
        _snapshot_values(
            ticker, second_date, status="stale", score=70.0, input_hash="c" * 64
        ),
    )
    await db_session.flush()

    by_date = await get_snapshot_by_date(db_session, ticker, first_date)
    latest = await get_latest_snapshot(db_session, ticker)
    latest_valid = await get_latest_valid_snapshot(db_session, ticker)
    history = await get_snapshot_history(db_session, ticker)
    older, newer = await compare_snapshots(
        db_session, ticker, first_date, second_date
    )

    assert same_inputs.id == first.id
    assert corrected_inputs.id != first.id
    assert by_date is not None and by_date.date == first_date
    assert latest is not None and latest.date == second_date
    assert latest_valid is not None and latest_valid.date == first_date
    assert [row.date for row in history] == [second_date, first_date, first_date]
    assert older is not None and older.date == first_date
    assert newer is not None and newer.date == second_date


def test_snapshot_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="unknown or managed"):
        from app.technical_analysis.repository import _snapshot_payload

        _snapshot_payload(
            {
                "ticker": "ABC.CA",
                "date": date(2025, 2, 3),
                "config_version": "test-v1",
                "input_hash": "d" * 64,
                "data_quality_status": "valid",
                "unexpected": 1,
            }
        )
