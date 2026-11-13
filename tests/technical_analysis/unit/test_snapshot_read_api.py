from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

from fastapi import FastAPI
from fastapi.testclient import TestClient

import app.technical_analysis.router as technical_router
from app.technical_analysis.dependencies import get_technical_session
from app.technical_analysis.schemas import TechnicalSnapshotRead


def _snapshot(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "ticker": "COMI.CA",
        "date": date(2026, 11, 12),
        "calculated_at": datetime(2026, 11, 12, 15, 30, tzinfo=UTC),
        "config_version": "v1",
        "input_hash": "a" * 64,
        "data_quality_status": "valid",
        "rsi": 54.2,
        "sma_20": 51.0,
        "sma_50": 48.0,
        "atr": 2.5,
        "setup_score": 67.0,
        "regime": "trending",
        "risk_label": "medium",
        "input_data": {"history_session_count": 260},
        "indicators": {"rsi14": 54.2},
        "scores": {"setup_score": {"score": 67.0}},
        "quality_flags": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(technical_router.router)

    async def fake_session():
        yield object()

    app.dependency_overrides[get_technical_session] = fake_session
    return TestClient(app)


def test_snapshot_response_schema_includes_version_and_provenance() -> None:
    payload = TechnicalSnapshotRead.model_validate(_snapshot()).model_dump(
        mode="json"
    )

    assert payload["schema_version"] == "technical-snapshot.v1"
    assert payload["provenance"]["source_table"] == "technical_snapshots"
    assert payload["provenance"]["input_hash"] == "a" * 64


def test_latest_snapshot_returns_quality_and_reproducibility_fields(monkeypatch) -> None:
    async def fake_latest(_session, ticker):
        assert ticker == "comi.ca"
        return _snapshot(data_quality_status="flagged", quality_flags=["stale"])

    monkeypatch.setattr(technical_router, "get_latest_snapshot", fake_latest)

    response = _client().get(
        "/api/v1/technical/comi.ca/snapshots/latest",
        headers={"X-User-ID": str(uuid4())},
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ticker"] == "COMI.CA"
    assert payload["data_quality_status"] == "flagged"
    assert payload["config_version"] == "v1"
    assert payload["input_hash"] == "a" * 64
    assert payload["schema_version"] == "technical-snapshot.v1"
    assert payload["provenance"] == {
        "source_table": "technical_snapshots",
        "config_version": "v1",
        "input_hash": "a" * 64,
    }
    assert payload["quality_flags"] == ["stale"]


def test_latest_valid_route_uses_valid_snapshot_repository_query(monkeypatch) -> None:
    async def fake_latest_valid(_session, ticker):
        assert ticker == "COMI.CA"
        return _snapshot()

    monkeypatch.setattr(
        technical_router,
        "get_latest_valid_snapshot",
        fake_latest_valid,
    )

    response = _client().get(
        "/api/v1/technical/COMI.CA/snapshots/latest-valid",
        headers={"X-User-ID": str(uuid4())},
    )

    assert response.status_code == 200
    assert response.json()["setup_score"] == 67.0


def test_snapshot_history_exposes_requested_bounds_and_count(monkeypatch) -> None:
    async def fake_history(_session, ticker, *, start_date, end_date, limit):
        assert (ticker, start_date, end_date, limit) == (
            "COMI.CA",
            date(2026, 11, 10),
            date(2026, 11, 12),
            20,
        )
        return [_snapshot()]

    monkeypatch.setattr(technical_router, "get_snapshot_history", fake_history)

    response = _client().get(
        "/api/v1/technical/COMI.CA/snapshots?from=2026-11-10&to=2026-11-12&limit=20",
        headers={"X-User-ID": str(uuid4())},
    )

    assert response.status_code == 200
    assert response.json()["count"] == 1
    assert response.json()["from_date"] == "2026-11-10"
    assert len(response.json()["snapshots"]) == 1


def test_snapshot_history_rejects_reversed_date_range() -> None:
    response = _client().get(
        "/api/v1/technical/COMI.CA/snapshots?from=2026-11-12&to=2026-11-10",
        headers={"X-User-ID": str(uuid4())},
    )

    assert response.status_code == 422


def test_snapshot_comparison_reports_missing_side_explicitly(monkeypatch) -> None:
    async def fake_compare(
        _session,
        ticker,
        first_date,
        second_date,
        *,
        config_version,
    ):
        assert ticker == "COMI.CA"
        assert first_date == date(2026, 11, 10)
        assert second_date == date(2026, 11, 12)
        assert config_version == "v1"
        return _snapshot(date=date(2026, 11, 10)), None

    monkeypatch.setattr(technical_router, "compare_snapshots", fake_compare)

    response = _client().get(
        "/api/v1/technical/COMI.CA/snapshots/compare?first=2026-11-10&second=2026-11-12&config_version=v1",
        headers={"X-User-ID": str(uuid4())},
    )

    assert response.status_code == 200
    assert response.json()["first"]["date"] == "2026-11-10"
    assert response.json()["second"] is None


def test_price_history_keeps_provider_source_and_adjusted_values(monkeypatch) -> None:
    price = SimpleNamespace(
        id=uuid4(),
        ticker="COMI.CA",
        date=date(2026, 11, 12),
        raw_open=Decimal("10.000000"),
        raw_high=Decimal("12.000000"),
        raw_low=Decimal("9.000000"),
        raw_close=Decimal("11.000000"),
        adj_open=Decimal("5.000000"),
        adj_high=Decimal("6.000000"),
        adj_low=Decimal("4.500000"),
        adj_close=Decimal("5.500000"),
        volume=1000,
        dividends=Decimal("0.250000"),
        stock_splits=Decimal("0.000000"),
        source="yahoo_finance",
        fetched_at=datetime(2026, 11, 12, 15, 30, tzinfo=UTC),
        created_at=datetime(2026, 11, 12, 15, 30, tzinfo=UTC),
        updated_at=datetime(2026, 11, 12, 15, 30, tzinfo=UTC),
    )

    async def fake_prices(_session, ticker, *, start_date, end_date, limit):
        assert ticker == "COMI.CA"
        return [price]

    monkeypatch.setattr(technical_router, "get_stock_price_history", fake_prices)

    response = _client().get(
        "/api/v1/technical/COMI.CA/prices?limit=10",
        headers={"X-User-ID": str(uuid4())},
    )

    assert response.status_code == 200
    payload = response.json()["prices"][0]
    assert payload["raw_close"] == "11.000000"
    assert payload["adj_close"] == "5.500000"
    assert payload["source"] == "yahoo_finance"


def test_read_routes_require_identity_header() -> None:
    response = _client().get("/api/v1/technical/COMI.CA/snapshots/latest")

    assert response.status_code == 422


def test_main_app_registers_technical_read_routes() -> None:
    from app.main import app

    paths = app.openapi()["paths"]
    assert "/api/v1/technical/{ticker}/snapshots/latest" in paths
    assert "/api/v1/technical/{ticker}/snapshots/latest-valid" in paths
    assert "/api/v1/technical/{ticker}/prices" in paths
