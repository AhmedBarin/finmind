from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal
from types import SimpleNamespace

import httpx
import pytest
import pytest_asyncio

import app.explanation.stock_qa.tools as tools_module
from app.core.dependencies import get_db_session
from app.explanation.router import get_stock_qa_service
from app.explanation.stock_qa.service import StockQAService
from app.explanation.stock_qa.tools import StockQATools
from app.main import app
from tests.auth_helpers import bearer_headers
from tests.explanation.unit.conftest import DATA_DATE, TODAY, make_snapshot

pytestmark = pytest.mark.asyncio


def _price(day: date, close: str = "82.15") -> SimpleNamespace:
    return SimpleNamespace(date=day, raw_close=Decimal(close), adj_close=Decimal(close), volume=1000)


@pytest.fixture
def fake_repos(monkeypatch):
    snapshot = make_snapshot()
    calls: dict[str, dict] = {}

    async def latest(session, ticker):
        return snapshot if ticker == "COMI.CA" else None

    async def by_date(session, ticker, on, config_version=None):
        return snapshot if (ticker, on) == ("COMI.CA", DATA_DATE) else None

    async def history(session, ticker, *, start_date=None, end_date=None, limit=None):
        calls["history"] = {"start": start_date, "end": end_date, "limit": limit}
        return [snapshot]

    async def latest_price(session, ticker):
        return _price(DATA_DATE) if ticker == "COMI.CA" else None

    async def price_history(session, ticker, *, start_date=None, end_date=None, limit=None):
        calls["prices"] = {"start": start_date, "end": end_date, "limit": limit}
        return [_price(DATA_DATE - timedelta(days=1), "81.5"), _price(DATA_DATE)]

    repo = tools_module.technical_repository
    monkeypatch.setattr(repo, "get_latest_snapshot", latest)
    monkeypatch.setattr(repo, "get_snapshot_by_date", by_date)
    monkeypatch.setattr(repo, "get_snapshot_history", history)
    monkeypatch.setattr(tools_module, "get_latest_stock_price", latest_price)
    monkeypatch.setattr(tools_module, "get_stock_price_history", price_history)
    return calls


async def test_snapshot_tool_returns_stored_values_without_input_window(fake_repos):
    result = await StockQATools(session=None).get_technical_snapshot("COMI.CA")
    assert result.found and result.data_date == DATA_DATE
    assert result.data["rsi"] == 56.2347
    assert result.data["date"] == "2026-11-16"
    assert result.data["indicators"]["adx14"] == 27.4
    assert "input_data" not in result.data


async def test_snapshot_tool_reports_missing(fake_repos):
    result = await StockQATools(session=None).get_technical_snapshot("HRHO.CA", date(2026, 1, 1))
    assert not result.found
    assert result.data == {"requested_date": "2026-01-01"}


async def test_snapshot_tool_by_date(fake_repos):
    result = await StockQATools(session=None).get_technical_snapshot("COMI.CA", DATA_DATE)
    assert result.found


async def test_price_history_anchors_period_to_latest_stored_price(fake_repos):
    result = await StockQATools(session=None).get_price_history("COMI.CA", "1m")
    assert fake_repos["prices"]["end"] == DATA_DATE
    assert fake_repos["prices"]["start"] == DATA_DATE - timedelta(days=31)
    assert [p["close"] for p in result.data["prices"]] == [81.5, 82.15]
    assert result.data_date == DATA_DATE


async def test_price_history_with_no_prices(fake_repos):
    result = await StockQATools(session=None).get_price_history("HRHO.CA", "1y")
    assert not result.found


async def test_snapshot_history_is_bounded(fake_repos):
    result = await StockQATools(session=None).get_snapshot_history("COMI.CA", None, DATA_DATE)
    assert fake_repos["history"]["limit"] == tools_module.SNAPSHOT_HISTORY_LIMIT
    assert result.data["snapshots"][0]["ticker"] == "COMI.CA"


async def test_compare_lists_missing_tickers(fake_repos):
    result = await StockQATools(session=None).compare_snapshots(["COMI.CA", "HRHO.CA"])
    assert [s["ticker"] for s in result.data["snapshots"]] == ["COMI.CA"]
    assert result.data["missing"] == ["HRHO.CA"]


async def test_glossary_tool():
    tools = StockQATools(session=None)
    assert (await tools.get_indicator_glossary("RSI")).data["name_ar"] == "مؤشر القوة النسبية"
    assert not (await tools.get_indicator_glossary("macd")).found


# ── Route ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(fake_repos):
    async def no_session():
        yield None

    app.dependency_overrides[get_db_session] = no_session
    app.dependency_overrides[get_stock_qa_service] = lambda: StockQAService(None, today=lambda: TODAY)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        yield http
    app.dependency_overrides.clear()


async def test_route_answers_with_template_when_no_llm(client):
    response = await client.post(
        "/api/v1/explanations/stock-qa",
        json={"question": "ما قيمة مؤشر القوة النسبية؟", "tickers": ["comi.ca"]},
        headers=bearer_headers(),
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["explanation_type"] == "stock_qa"
    assert body["tickers"] == ["COMI.CA"]
    assert body["data_date"] == "2026-11-16"
    assert body["generation"] == "fallback"
    assert body["disclaimer_ar"]


@pytest.mark.parametrize(
    "payload",
    [
        {"question": "", "tickers": ["COMI.CA"]},
        {"question": "RSI?", "tickers": []},
        {"question": "RSI?", "tickers": ["../etc"]},
        {"question": "RSI?", "tickers": ["A", "B", "C", "D", "E", "F"]},
        {"question": "x" * 1001, "tickers": ["COMI.CA"]},
        {"question": "RSI?", "tickers": ["COMI.CA"], "period": "10y"},
        {"question": "RSI?", "tickers": ["COMI.CA"], "extra": 1},
    ],
)
async def test_route_rejects_invalid_requests(client, payload):
    response = await client.post(
        "/api/v1/explanations/stock-qa", json=payload, headers=bearer_headers()
    )
    assert response.status_code == 422
