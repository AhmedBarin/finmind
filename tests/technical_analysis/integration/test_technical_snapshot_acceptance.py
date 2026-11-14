from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, timedelta
from decimal import Decimal
import json
from uuid import uuid4

import httpx
import pandas as pd
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal, engine
from app.main import app
from app.market_data.fetcher import FetchedPriceHistory
from app.market_data.ingestion import ingest_price_history
from app.market_data.models import StockPrice
from app.technical_analysis.dependencies import get_technical_session
from app.technical_analysis.snapshot_service import calculate_and_persist_snapshot


@pytest_asyncio.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
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
        # EGX sessions are Sunday through Thursday in the current calendar config.
        if current.weekday() in {6, 0, 1, 2, 3}:
            sessions.append(current)
        current += timedelta(days=1)
    return sessions


def _price_rows(ticker: str, sessions: list[date]) -> list[StockPrice]:
    rows: list[StockPrice] = []
    for index, session_date in enumerate(sessions):
        close = Decimal(f"{20 + index * 0.04:.6f}")
        factor = Decimal("0.95")
        rows.append(
            StockPrice(
                ticker=ticker,
                date=session_date,
                raw_open=close,
                raw_high=close * Decimal("1.02"),
                raw_low=close * Decimal("0.98"),
                raw_close=close,
                adj_open=close * factor,
                adj_high=close * Decimal("1.02") * factor,
                adj_low=close * Decimal("0.98") * factor,
                adj_close=close * factor,
                volume=100_000 + index * 10,
                dividends=Decimal("0"),
                stock_splits=Decimal("0"),
                source="technical-acceptance-test",
            )
        )
    return rows


def _provider_history(ticker: str, sessions: list[date]) -> FetchedPriceHistory:
    rows = []
    for index, session_date in enumerate(sessions):
        close = 20 + index * 0.04
        rows.append(
            {
                "Open": close,
                "High": close * 1.02,
                "Low": close * 0.98,
                "Close": close,
                "Adj Close": close * 0.95,
                "Volume": 100_000 + index * 10,
                "Dividends": 0,
                "Stock Splits": 0,
            }
        )
    frame = pd.DataFrame(rows, index=pd.DatetimeIndex(sessions, name="Date"))
    return FetchedPriceHistory(ticker=ticker, source="acceptance-test", prices=frame)


@pytest.mark.asyncio
async def test_stored_prices_produce_valid_snapshot_readable_through_api(
    db_session: AsyncSession,
) -> None:
    ticker = f"T{uuid4().hex[:10]}".upper()
    sessions = _egx_sessions(300)
    db_session.add_all(_price_rows(ticker, sessions))
    await db_session.flush()

    snapshot = await calculate_and_persist_snapshot(
        db_session,
        ticker,
        sessions[-1],
        expected_trading_sessions=sessions,
    )
    await db_session.flush()
    assert snapshot.data_quality_status == "valid"

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_technical_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-User-ID": str(uuid4())},
        ) as client:
            response = await client.get(
                f"/api/v1/technical/{ticker}/snapshots/latest-valid"
            )
    finally:
        app.dependency_overrides.pop(get_technical_session, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(snapshot.id)
    assert payload["ticker"] == ticker
    assert payload["date"] == sessions[-1].isoformat()
    assert payload["data_quality_status"] == "valid"
    assert payload["config_version"] == snapshot.config_version
    assert payload["input_hash"] == snapshot.input_hash
    assert payload["schema_version"] == "technical-snapshot.v1"
    assert payload["provenance"]["input_hash"] == snapshot.input_hash
    assert payload["input_data"]["history_session_count"] == 300
    assert payload["indicators"]["rsi14"] is not None
    assert payload["scores"]["family_scores"]


@pytest.mark.asyncio
async def test_insufficient_history_is_visible_but_not_read_as_latest_valid(
    db_session: AsyncSession,
) -> None:
    ticker = f"T{uuid4().hex[:10]}".upper()
    as_of_date = date(2026, 11, 13)
    snapshot = await calculate_and_persist_snapshot(
        db_session,
        ticker,
        as_of_date,
        expected_trading_sessions=[],
    )
    await db_session.flush()
    assert snapshot.data_quality_status == "insufficient_history"

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_technical_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-User-ID": str(uuid4())},
        ) as client:
            latest_response = await client.get(
                f"/api/v1/technical/{ticker}/snapshots/latest"
            )
            valid_response = await client.get(
                f"/api/v1/technical/{ticker}/snapshots/latest-valid"
            )
    finally:
        app.dependency_overrides.pop(get_technical_session, None)

    assert latest_response.status_code == 200
    assert latest_response.json()["data_quality_status"] == "insufficient_history"
    assert valid_response.status_code == 404


@pytest.mark.asyncio
async def test_full_offline_engine_flow_prints_snapshot(
    db_session: AsyncSession,
) -> None:
    """Exercise fetched-data shape -> ingestion -> snapshot -> database -> API."""
    ticker = f"T{uuid4().hex[:10]}".upper()
    sessions = _egx_sessions(300)

    report = await ingest_price_history(
        db_session,
        _provider_history(ticker, sessions),
    )
    assert report.inserted == 300
    assert report.updated == 0
    assert report.unchanged == 0

    snapshot = await calculate_and_persist_snapshot(
        db_session,
        ticker,
        sessions[-1],
        expected_trading_sessions=sessions,
    )
    await db_session.flush()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_technical_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-User-ID": str(uuid4())},
        ) as client:
            response = await client.get(
                f"/api/v1/technical/{ticker}/snapshots/latest-valid"
            )
    finally:
        app.dependency_overrides.pop(get_technical_session, None)

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == str(snapshot.id)
    assert payload["data_quality_status"] == "valid"
    assert payload["indicators"]["rsi14"] is not None
    assert payload["scores"]["setup_score"] is not None

    print("\nTechnical Engine end-to-end snapshot:")
    print(json.dumps(payload, indent=2, sort_keys=True))
