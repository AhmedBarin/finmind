from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio

from app.db.session import SessionLocal, engine
from app.market_data.models import StockPrice
from app.technical_analysis.snapshot_service import calculate_and_persist_snapshot


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


def _egx_sessions(count: int) -> list[date]:
    sessions: list[date] = []
    current = date(2024, 1, 1)
    while len(sessions) < count:
        if current.weekday() in {6, 0, 1, 2, 3}:
            sessions.append(current)
        current += timedelta(days=1)
    return sessions


def _price_rows(ticker: str, dates: list[date]) -> list[StockPrice]:
    rows: list[StockPrice] = []
    for index, session_date in enumerate(dates):
        close = Decimal(f"{20 + index * 0.04:.6f}")
        high = close * Decimal("1.02")
        low = close * Decimal("0.98")
        adj_close = close * Decimal("0.95")
        rows.append(
            StockPrice(
                ticker=ticker,
                date=session_date,
                raw_open=close,
                raw_high=high,
                raw_low=low,
                raw_close=close,
                adj_open=close * Decimal("0.95"),
                adj_high=high * Decimal("0.95"),
                adj_low=low * Decimal("0.95"),
                adj_close=adj_close,
                volume=100_000 + index * 10,
                dividends=Decimal("0"),
                stock_splits=Decimal("0"),
                source="pipeline-test",
            )
        )
    return rows


@pytest.mark.asyncio
async def test_pipeline_calculates_and_persists_reproducible_snapshot(db_session) -> None:
    ticker = f"T{uuid4().hex[:10]}".upper()
    sessions = _egx_sessions(300)
    price_rows = _price_rows(ticker, sessions)
    db_session.add_all(price_rows)
    await db_session.flush()

    snapshot = await calculate_and_persist_snapshot(
        db_session,
        ticker,
        sessions[-1],
        expected_trading_sessions=sessions,
    )
    await db_session.flush()

    assert snapshot.ticker == ticker
    assert snapshot.date == sessions[-1]
    assert snapshot.data_quality_status == "valid"
    assert snapshot.regime in {"trending", "transition", "ranging"}
    assert snapshot.rsi is not None
    assert snapshot.sma_20 is not None
    assert snapshot.sma_50 is not None
    assert snapshot.atr is not None
    assert snapshot.setup_score is not None
    assert len(snapshot.input_data["source_window"]) == 300
    assert snapshot.indicators["liquidity_rank_pct"] is None
    assert set(snapshot.scores["family_scores"]) == {
        "trend",
        "momentum",
        "volume",
        "support_resistance",
    }

    repeated = await calculate_and_persist_snapshot(
        db_session,
        ticker,
        sessions[-1],
        expected_trading_sessions=sessions,
    )
    assert repeated.id == snapshot.id

    last_price = price_rows[-1]
    for field in ("raw_open", "raw_high", "raw_low", "raw_close"):
        setattr(last_price, field, getattr(last_price, field) * Decimal("1.01"))
    for field in ("adj_open", "adj_high", "adj_low", "adj_close"):
        setattr(last_price, field, getattr(last_price, field) * Decimal("1.01"))
    await db_session.flush()

    corrected = await calculate_and_persist_snapshot(
        db_session,
        ticker,
        sessions[-1],
        expected_trading_sessions=sessions,
    )
    assert corrected.id != snapshot.id


@pytest.mark.asyncio
async def test_pipeline_persists_insufficient_history_snapshot(db_session) -> None:
    ticker = f"T{uuid4().hex[:10]}".upper()
    snapshot = await calculate_and_persist_snapshot(
        db_session,
        ticker,
        date(2025, 1, 5),
        expected_trading_sessions=[],
    )

    assert snapshot.data_quality_status == "insufficient_history"
    assert snapshot.setup_score is None
    assert snapshot.input_data["source_window"] == []
