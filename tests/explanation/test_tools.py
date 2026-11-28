"""Tests for the 5 read-only snapshot tools (REQ-032)."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from app.explanation.tools import (
    IndicatorGlossaryTool,
    PriceHistoryTool,
    SnapshotComparisonTool,
    SnapshotHistoryTool,
    TechnicalSnapshotTool,
    build_default_tools,
)

# ── Fake domain objects ──────────────────────────────────────────────────


@dataclass
class FakeSnapshot:
    id: Any = None
    ticker: str = "COMI"
    date: date = date(2026, 11, 20)
    calculated_at: datetime = datetime(2026, 11, 20, 14, 0, tzinfo=UTC)
    config_version: str = "v1"
    input_hash: str = "abc123"
    data_quality_status: str = "valid"
    rsi: float | None = 55.0
    sma_20: float | None = 42.5
    sma_50: float | None = 40.0
    atr: float | None = 1.2
    setup_score: float | None = 72.0
    regime: str | None = "bullish"
    risk_label: str | None = "moderate"
    input_data: dict = None
    indicators: dict = None
    scores: dict = None
    quality_flags: list = None

    def __post_init__(self) -> None:
        self.id = self.id or uuid4()
        self.input_data = self.input_data or {}
        self.indicators = self.indicators or {}
        self.scores = self.scores or {}
        self.quality_flags = self.quality_flags or []


@dataclass
class FakePrice:
    id: Any = None
    ticker: str = "COMI"
    date: date = date(2026, 11, 20)
    raw_open: Decimal | None = Decimal("42.0")
    raw_high: Decimal | None = Decimal("43.5")
    raw_low: Decimal | None = Decimal("41.5")
    raw_close: Decimal | None = Decimal("43.0")
    adj_open: Decimal | None = Decimal("42.0")
    adj_high: Decimal | None = Decimal("43.5")
    adj_low: Decimal | None = Decimal("41.5")
    adj_close: Decimal | None = Decimal("43.0")
    volume: int | None = 1_500_000
    dividends: Decimal | None = None
    stock_splits: Decimal | None = None
    source: str = "yfinance"
    fetched_at: datetime = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)
    created_at: datetime = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)
    updated_at: datetime = datetime(2026, 11, 20, 15, 0, tzinfo=UTC)

    def __post_init__(self) -> None:
        self.id = self.id or uuid4()


# ── Fake repos ───────────────────────────────────────────────────────────


class FakeSnapshotRepo:
    def __init__(self, snapshots: dict[str, list[FakeSnapshot]] | None = None) -> None:
        self._data = snapshots or {}

    async def get_latest_snapshot(self, ticker: str) -> FakeSnapshot | None:
        items = self._data.get(ticker, [])
        return items[-1] if items else None

    async def get_snapshot_history(
        self, ticker: str, *, days: int = 30
    ) -> list[FakeSnapshot]:
        return self._data.get(ticker, [])


class FakePriceRepo:
    def __init__(self, prices: dict[str, list[FakePrice]] | None = None) -> None:
        self._data = prices or {}

    async def get_price_history(
        self, ticker: str, *, days: int = 30
    ) -> list[FakePrice]:
        return self._data.get(ticker, [])


class ErrorSnapshotRepo:
    async def get_latest_snapshot(self, ticker: str) -> None:
        raise RuntimeError("DB connection failed")

    async def get_snapshot_history(self, ticker: str, *, days: int = 30) -> list:
        raise RuntimeError("DB connection failed")


class ErrorPriceRepo:
    async def get_price_history(self, ticker: str, *, days: int = 30) -> list:
        raise RuntimeError("DB connection failed")


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestTechnicalSnapshotTool:
    @pytest.mark.asyncio
    async def test_returns_snapshot_data(self) -> None:
        snap = FakeSnapshot(ticker="COMI", rsi=55.0)
        tool = TechnicalSnapshotTool(FakeSnapshotRepo({"COMI": [snap]}))

        result = await tool.invoke({"ticker": "comi"})

        assert result["status"] == "ok"
        assert result["ticker"] == "COMI"
        assert result["data_date"] is not None
        assert result["freshness_seconds"] is not None
        assert result["snapshot"]["rsi"] == 55.0

    @pytest.mark.asyncio
    async def test_not_found(self) -> None:
        tool = TechnicalSnapshotTool(FakeSnapshotRepo())

        result = await tool.invoke({"ticker": "XXXX"})

        assert result["status"] == "not_found"
        assert result["data_date"] is None

    @pytest.mark.asyncio
    async def test_stale_data(self) -> None:
        snap = FakeSnapshot(data_quality_status="stale")
        tool = TechnicalSnapshotTool(FakeSnapshotRepo({"COMI": [snap]}))

        result = await tool.invoke({"ticker": "COMI"})

        assert result["status"] == "stale"

    @pytest.mark.asyncio
    async def test_error_handling(self) -> None:
        tool = TechnicalSnapshotTool(ErrorSnapshotRepo())

        result = await tool.invoke({"ticker": "COMI"})

        assert result["status"] == "unavailable"
        assert "error" in result


class TestSnapshotHistoryTool:
    @pytest.mark.asyncio
    async def test_returns_history(self) -> None:
        snaps = [
            FakeSnapshot(date=date(2026, 11, 18)),
            FakeSnapshot(date=date(2026, 11, 20)),
        ]
        tool = SnapshotHistoryTool(FakeSnapshotRepo({"COMI": snaps}))

        result = await tool.invoke({"ticker": "COMI", "days": 30})

        assert result["status"] == "ok"
        assert result["count"] == 2
        assert len(result["snapshots"]) == 2

    @pytest.mark.asyncio
    async def test_empty_history(self) -> None:
        tool = SnapshotHistoryTool(FakeSnapshotRepo())

        result = await tool.invoke({"ticker": "COMI"})

        assert result["status"] == "not_found"
        assert result["count"] == 0

    @pytest.mark.asyncio
    async def test_caps_days_at_90(self) -> None:
        tool = SnapshotHistoryTool(FakeSnapshotRepo())
        # Should not raise even with days > 90
        result = await tool.invoke({"ticker": "COMI", "days": 365})
        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_error_handling(self) -> None:
        tool = SnapshotHistoryTool(ErrorSnapshotRepo())

        result = await tool.invoke({"ticker": "COMI"})

        assert result["status"] == "unavailable"


class TestPriceHistoryTool:
    @pytest.mark.asyncio
    async def test_returns_prices(self) -> None:
        prices = [
            FakePrice(date=date(2026, 11, 19)),
            FakePrice(date=date(2026, 11, 20)),
        ]
        tool = PriceHistoryTool(FakePriceRepo({"COMI": prices}))

        result = await tool.invoke({"ticker": "COMI", "days": 7})

        assert result["status"] == "ok"
        assert result["count"] == 2
        assert result["prices"][0]["close"] == 43.0

    @pytest.mark.asyncio
    async def test_empty_prices(self) -> None:
        tool = PriceHistoryTool(FakePriceRepo())

        result = await tool.invoke({"ticker": "COMI"})

        assert result["status"] == "not_found"

    @pytest.mark.asyncio
    async def test_error_handling(self) -> None:
        tool = PriceHistoryTool(ErrorPriceRepo())

        result = await tool.invoke({"ticker": "COMI"})

        assert result["status"] == "unavailable"


class TestSnapshotComparisonTool:
    @pytest.mark.asyncio
    async def test_compares_multiple_tickers(self) -> None:
        repo = FakeSnapshotRepo(
            {
                "COMI": [FakeSnapshot(ticker="COMI", rsi=55.0)],
                "SWDY": [FakeSnapshot(ticker="SWDY", rsi=70.0)],
            }
        )
        tool = SnapshotComparisonTool(repo)

        result = await tool.invoke({"tickers": ["COMI", "SWDY"]})

        assert result["status"] == "ok"
        assert len(result["comparisons"]) == 2

    @pytest.mark.asyncio
    async def test_partial_data(self) -> None:
        repo = FakeSnapshotRepo(
            {
                "COMI": [FakeSnapshot(ticker="COMI")],
            }
        )
        tool = SnapshotComparisonTool(repo)

        result = await tool.invoke({"tickers": ["COMI", "XXXX"]})

        assert result["status"] == "ok"  # at least one found
        statuses = [c["status"] for c in result["comparisons"]]
        assert "not_found" in statuses

    @pytest.mark.asyncio
    async def test_all_not_found(self) -> None:
        tool = SnapshotComparisonTool(FakeSnapshotRepo())

        result = await tool.invoke({"tickers": ["XXXX", "YYYY"]})

        assert result["status"] == "not_found"


class TestIndicatorGlossaryTool:
    @pytest.mark.asyncio
    async def test_returns_all_indicators(self) -> None:
        tool = IndicatorGlossaryTool()

        result = await tool.invoke({})

        assert result["status"] == "ok"
        assert result["freshness_seconds"] == 0
        assert "RSI" in result["indicators"]
        assert "SMA_20" in result["indicators"]
        assert "ATR" in result["indicators"]
        assert "SETUP_SCORE" in result["indicators"]
        assert "REGIME" in result["indicators"]

    @pytest.mark.asyncio
    async def test_glossary_has_arabic_descriptions(self) -> None:
        tool = IndicatorGlossaryTool()
        result = await tool.invoke({})

        rsi = result["indicators"]["RSI"]
        assert "name_ar" in rsi
        assert "description_ar" in rsi


class TestBuildDefaultTools:
    def test_returns_5_tools(self) -> None:
        tools = build_default_tools()
        assert len(tools) == 5

    def test_tool_names_are_unique(self) -> None:
        tools = build_default_tools()
        names = [t.name for t in tools]
        assert len(set(names)) == 5

    def test_expected_tool_names(self) -> None:
        tools = build_default_tools()
        names = {t.name for t in tools}
        expected = {
            "technical_snapshot",
            "snapshot_history",
            "price_history",
            "snapshot_comparison",
            "indicator_glossary",
        }
        assert names == expected
