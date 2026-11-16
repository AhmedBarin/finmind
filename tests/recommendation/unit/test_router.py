from __future__ import annotations

import asyncio
from datetime import date, datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

import app.recommendation.router as recommendation_router
from app.recommendation.dependencies import get_recommendation_session
from app.recommendation.schemas import (
    ConfidenceLevel,
    RecommendationDecision,
    RecommendationDataQuality,
    RecommendationResult,
)


def _result() -> RecommendationResult:
    return RecommendationResult(
        ticker="COMI.CA",
        trading_date=date(2026, 11, 12),
        config_version="recommendation-v1",
        decision=RecommendationDecision.WATCH,
        reasons=["trend"],
        confidence=ConfidenceLevel.LOW,
        data_quality=RecommendationDataQuality(
            price_status="valid", last_price_date=date(2026, 11, 12)
        ),
    )


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(recommendation_router.router)

    async def fake_session():
        yield object()

    app.dependency_overrides[get_recommendation_session] = fake_session
    return app


def _audit(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "user_id": uuid4(),
        "ticker": "COMI.CA",
        "trading_date": date(2026, 11, 12),
        "snapshot_id": uuid4(),
        "config_version": "recommendation-v1",
        "decision": "WATCH",
        "blockers": ["trend"],
        "confidence": "Low",
        "created_at": datetime(2026, 11, 12, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


@pytest.mark.asyncio
async def test_evaluate_endpoint_returns_result_and_audit_id(monkeypatch) -> None:
    user_id = uuid4()

    async def fake_load(_session, *, user_id: object, ticker: str):
        assert user_id == user_id_expected
        assert ticker == "COMI.CA"
        return object()

    user_id_expected = user_id
    monkeypatch.setattr(recommendation_router, "load_recommendation_inputs", fake_load)
    monkeypatch.setattr(recommendation_router, "evaluate_decision", lambda _inputs: object())
    monkeypatch.setattr(
        recommendation_router,
        "build_recommendation_result",
        lambda _inputs, _evaluation: _result(),
    )

    async def fake_save(_session, *, user_id: object, result: RecommendationResult):
        assert user_id == user_id_expected
        assert result.ticker == "COMI.CA"
        return _audit(user_id=user_id)

    monkeypatch.setattr(recommendation_router.repository, "save_recommendation_log", fake_save)

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await asyncio.wait_for(client.post(
            "/api/v1/recommendations",
            headers={"X-User-ID": str(user_id)},
            json={"ticker": "comi.ca"},
        ), timeout=5)

    assert response.status_code == 200
    payload = response.json()
    assert payload["recommendation_id"]
    assert payload["result"]["ticker"] == "COMI.CA"
    assert payload["result"]["decision"] == "WATCH"
    assert payload["result"]["data_quality"]["price_status"] == "valid"


@pytest.mark.asyncio
async def test_history_is_user_scoped_and_returns_audit_fields(monkeypatch) -> None:
    user_id = uuid4()
    row = _audit(user_id=user_id)

    async def fake_history(_session, *, user_id: object, ticker: str | None, limit: int):
        assert user_id == user_id_expected
        assert ticker == "COMI.CA"
        assert limit == 10
        return [row]

    user_id_expected = user_id
    monkeypatch.setattr(
        recommendation_router.repository,
        "get_recommendation_history",
        fake_history,
    )

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            "/api/v1/recommendations/history?ticker=COMI.CA&limit=10",
            headers={"X-User-ID": str(user_id)},
        )

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["recommendations"][0]["blockers"] == ["trend"]


@pytest.mark.asyncio
async def test_retrieve_hides_audit_rows_owned_by_another_user(monkeypatch) -> None:
    user_id = uuid4()

    async def fake_get(_session, *, user_id: object, recommendation_id: object):
        assert user_id == user_id_expected
        assert recommendation_id == recommendation_id_expected
        return None

    user_id_expected = user_id
    recommendation_id_expected = uuid4()
    monkeypatch.setattr(
        recommendation_router.repository,
        "get_recommendation_by_id",
        fake_get,
    )

    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(
            f"/api/v1/recommendations/{recommendation_id_expected}",
            headers={"X-User-ID": str(user_id)},
        )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_recommendation_routes_require_identity_header() -> None:
    transport = httpx.ASGITransport(app=_app())
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/v1/recommendations/history")

    assert response.status_code == 422


def test_main_app_registers_recommendation_routes() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/v1/recommendations" in paths
    assert "/api/v1/recommendations/history" in paths
    assert "/api/v1/recommendations/{recommendation_id}" in paths
