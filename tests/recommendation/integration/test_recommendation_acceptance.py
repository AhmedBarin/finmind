from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import date, timedelta
import json
from uuid import uuid4

import httpx
import pandas as pd
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.models import Company
from app.db.session import SessionLocal, engine
from app.investor.models import InvestorProfile
from app.investor.schemas import (
    InvestmentExperience,
    InvestmentGoal,
    InvestmentHorizon,
    RiskProfile,
)
from app.main import app
from app.market_data.fetcher import FetchedPriceHistory
from app.market_data.ingestion import ingest_price_history
from app.recommendation.dependencies import get_recommendation_session
from app.technical_analysis.liquidity_ranker import rank_egx30_snapshots
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


def _sessions(count: int) -> list[date]:
    result: list[date] = []
    current = date(2024, 1, 1)
    while len(result) < count:
        if current.weekday() in {6, 0, 1, 2, 3}:
            result.append(current)
        current += timedelta(days=1)
    return result


def _provider_history(
    ticker: str,
    dates: list[date],
    *,
    volume_base: int,
) -> FetchedPriceHistory:
    rows = []
    for index, trading_date in enumerate(dates):
        close = 20 + index * 0.04
        rows.append(
            {
                "Open": close,
                "High": close * 1.02,
                "Low": close * 0.98,
                "Close": close,
                "Adj Close": close * 0.95,
                "Volume": volume_base + index * 10,
                "Dividends": 0,
                "Stock Splits": 0,
            }
        )
    return FetchedPriceHistory(
        ticker=ticker,
        source="recommendation-acceptance-test",
        prices=pd.DataFrame(rows, index=pd.DatetimeIndex(dates, name="Date")),
    )


@pytest.mark.asyncio
async def test_ingested_egx30_ranked_snapshot_returns_and_logs_recommendation(
    db_session: AsyncSession,
) -> None:
    """Exercise ingestion -> snapshots -> EGX30 rank -> evaluate API -> audit reads."""
    ticker = f"T{uuid4().hex[:10]}".upper() + ".CA"
    other_ticker = f"T{uuid4().hex[:10]}".upper() + ".CA"
    user_id = uuid4()
    dates = _sessions(300)

    db_session.add_all(
        [
            Company(
                ticker=ticker.removesuffix(".CA"),
                name_en=f"Acceptance {ticker}",
                sector="Financial Services",
            ),
            Company(
                ticker=other_ticker.removesuffix(".CA"),
                name_en=f"Acceptance {other_ticker}",
                sector="Financial Services",
            ),
            InvestorProfile(
                user_id=user_id,
                risk_profile=RiskProfile.MODERATE.value,
                investment_horizon=InvestmentHorizon.MEDIUM.value,
                investment_goal=InvestmentGoal.GROWTH.value,
                investment_experience=InvestmentExperience.INTERMEDIATE.value,
                liquidity_floor_pct=70,
                max_atr_pctl_cap=75,
                is_active=True,
                profile_version=1,
            ),
        ]
    )
    await db_session.flush()

    for symbol, volume_base in ((ticker, 250_000), (other_ticker, 100_000)):
        history = _provider_history(symbol, dates, volume_base=volume_base)
        ingestion = await ingest_price_history(db_session, history)
        assert ingestion.inserted == 300
        snapshot = await calculate_and_persist_snapshot(
            db_session,
            symbol,
            dates[-1],
            expected_trading_sessions=dates,
        )
        assert snapshot.data_quality_status == "valid"

    rank_report = await rank_egx30_snapshots(
        db_session,
        dates[-1],
        universe_tickers=(ticker, other_ticker),
        universe_version="acceptance-test-v1",
    )
    assert ticker in rank_report.ranked_tickers
    await db_session.flush()

    async def override_session() -> AsyncIterator[AsyncSession]:
        yield db_session

    app.dependency_overrides[get_recommendation_session] = override_session
    try:
        transport = httpx.ASGITransport(app=app)
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://test",
            headers={"X-User-ID": str(user_id)},
        ) as client:
            evaluated = await client.post(
                "/api/v1/recommendations",
                json={"ticker": ticker.lower()},
            )
            assert evaluated.status_code == 200, evaluated.text
            evaluation_payload = evaluated.json()

            recommendation_id = evaluation_payload["recommendation_id"]
            retrieved = await client.get(
                f"/api/v1/recommendations/{recommendation_id}"
            )
            history = await client.get(
                f"/api/v1/recommendations/history?ticker={ticker}"
            )
    finally:
        app.dependency_overrides.pop(get_recommendation_session, None)

    result = evaluation_payload["result"]
    assert result["ticker"] == ticker
    assert result["trading_date"] == dates[-1].isoformat()
    assert result["data_quality"]["price_status"] == "valid"
    assert result["indicators"]["liquidity_rank_pct"] == 100.0
    assert retrieved.status_code == 200
    assert retrieved.json()["id"] == recommendation_id
    assert retrieved.json()["snapshot_id"] == result["snapshot_id"]
    assert history.status_code == 200
    assert history.json()["count"] == 1
    assert history.json()["recommendations"][0]["decision"] == result["decision"]

    print("\nRecommendation Engine end-to-end result:")
    print(json.dumps(evaluation_payload, indent=2, sort_keys=True))
