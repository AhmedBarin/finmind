from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from types import SimpleNamespace
from uuid import uuid4

import pytest

import app.explanation.tools as tools
from app.market_data.calendar import OfficialEGXHoliday, VerifiedEGXCalendar


OFFICIAL_REFERENCE = "https://beta.egx.com.eg/en/media-center"


def _snapshot(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "ticker": "COMI.CA",
        "date": date(2026, 11, 16),
        "calculated_at": datetime(2026, 11, 16, 15, 30, tzinfo=UTC),
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
        "input_data": {
            "history_session_count": 260,
            "source_window": [{"close": 1.0}] * 1000,
        },
        "indicators": {"rsi14": 54.2},
        "scores": {"setup_score": {"score": 67.0}},
        "quality_flags": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _price(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "ticker": "COMI.CA",
        "date": date(2026, 11, 24),
        "raw_open": Decimal("10.000000"),
        "raw_high": Decimal("12.000000"),
        "raw_low": Decimal("9.000000"),
        "raw_close": Decimal("11.000000"),
        "adj_open": Decimal("5.000000"),
        "adj_high": Decimal("6.000000"),
        "adj_low": Decimal("4.500000"),
        "adj_close": Decimal("5.500000"),
        "volume": 1000,
        "dividends": Decimal("0"),
        "stock_splits": Decimal("0"),
        "source": "yahoo_finance",
        "fetched_at": datetime(2026, 11, 24, 15, 30, tzinfo=UTC),
        "created_at": datetime(2026, 11, 24, 15, 30, tzinfo=UTC),
        "updated_at": datetime(2026, 11, 24, 15, 30, tzinfo=UTC),
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _calendar(start: date, through: date, *holidays: date) -> VerifiedEGXCalendar:
    return VerifiedEGXCalendar(
        coverage_start=start,
        verified_through=through,
        verification_reference_urls=(OFFICIAL_REFERENCE,),
        holidays=tuple(
            OfficialEGXHoliday(
                holiday_date=holiday,
                holiday_name="Official EGX closure",
                announcement_url=OFFICIAL_REFERENCE,
            )
            for holiday in holidays
        ),
    )


@pytest.mark.asyncio
async def test_freshness_is_fresh_at_two_trading_sessions(monkeypatch) -> None:
    async def calendar(_session, start_date, end_date):
        assert start_date == date(2026, 11, 17)
        assert end_date == date(2026, 11, 18)
        return _calendar(start_date, end_date)

    monkeypatch.setattr(tools, "get_verified_egx_calendar", calendar)

    freshness, age, limitations = await tools._freshness(
        object(), date(2026, 11, 16), as_of_date=date(2026, 11, 18)
    )

    assert (freshness, age, limitations) == ("fresh", 2, [])


@pytest.mark.asyncio
async def test_data_older_than_two_sessions_is_stale_and_warns(monkeypatch) -> None:
    async def calendar(_session, start_date, end_date):
        return _calendar(start_date, end_date)

    monkeypatch.setattr(tools, "get_verified_egx_calendar", calendar)

    freshness, age, limitations = await tools._freshness(
        object(), date(2026, 11, 16), as_of_date=date(2026, 11, 19)
    )

    assert freshness == "stale"
    assert age == 3
    assert limitations and "أقدم" in limitations[0]


@pytest.mark.asyncio
async def test_official_holiday_does_not_count_as_a_trading_session(monkeypatch) -> None:
    async def calendar(_session, start_date, end_date):
        return _calendar(start_date, end_date, date(2026, 11, 23))

    monkeypatch.setattr(tools, "get_verified_egx_calendar", calendar)

    freshness, age, _ = await tools._freshness(
        object(), date(2026, 11, 19), as_of_date=date(2026, 11, 24)
    )

    # Friday and Saturday are weekends; Sunday and Tuesday are sessions.
    assert (freshness, age) == ("fresh", 2)


@pytest.mark.asyncio
async def test_missing_official_calendar_coverage_does_not_assume_no_holidays(monkeypatch) -> None:
    async def no_coverage(*_args):
        return None

    monkeypatch.setattr(tools, "get_verified_egx_calendar", no_coverage)

    freshness, age, limitations = await tools._freshness(
        object(), date(2026, 11, 16), as_of_date=date(2026, 11, 18)
    )

    assert freshness == "unavailable"
    assert age is None
    assert limitations and "تغطية تقويم" in limitations[0]


@pytest.mark.asyncio
async def test_weekend_days_are_excluded_without_requiring_holiday_coverage(monkeypatch) -> None:
    async def unexpected_calendar(*_args):
        raise AssertionError("weekend-only age must not require holiday coverage")

    monkeypatch.setattr(tools, "get_verified_egx_calendar", unexpected_calendar)

    freshness, age, limitations = await tools._freshness(
        object(), date(2026, 11, 19), as_of_date=date(2026, 11, 21)
    )

    assert (freshness, age, limitations) == ("fresh", 0, [])


@pytest.mark.asyncio
async def test_snapshot_tool_uses_exact_date_and_returns_bounded_provenance(monkeypatch) -> None:
    async def snapshot(_session, ticker, snapshot_date):
        assert ticker == "COMI.CA"
        assert snapshot_date == date(2026, 11, 16)
        return _snapshot()

    async def no_calendar(*_args):
        return None

    monkeypatch.setattr(tools, "get_snapshot_by_date", snapshot)
    monkeypatch.setattr(tools, "get_verified_egx_calendar", no_calendar)

    result = await tools.get_technical_snapshot_data(
        object(), "comi.ca", date(2026, 11, 16), as_of_date=date(2026, 11, 18)
    )

    assert result["tool"] == "get_technical_snapshot"
    assert result["tickers"] == ["COMI.CA"]
    assert result["data_date"] == "2026-11-16"
    assert result["status"] == "partial"
    assert "source_window" not in result["payload"]["input_data"]


@pytest.mark.asyncio
async def test_snapshot_history_tool_uses_repository_bounds_and_default_limit(monkeypatch) -> None:
    async def history(_session, ticker, *, start_date, end_date, limit):
        assert ticker == "COMI.CA"
        assert (start_date, end_date, limit) == (
            date(2026, 11, 20),
            date(2026, 11, 24),
            100,
        )
        return [_snapshot(date=date(2026, 11, 24))]

    monkeypatch.setattr(tools, "get_snapshot_history", history)

    result = await tools.get_snapshot_history_data(
        object(), "comi.ca", from_date=date(2026, 11, 20), as_of_date=date(2026, 11, 24)
    )

    assert result["status"] == "available"
    assert result["payload"]["count"] == 1
    assert result["data_date"] == "2026-11-24"


@pytest.mark.asyncio
async def test_price_history_maps_period_to_inclusive_repository_bounds(monkeypatch) -> None:
    async def prices(_session, ticker, *, start_date, end_date, limit):
        assert ticker == "COMI.CA"
        assert (start_date, end_date, limit) == (
            date(2026, 10, 24),
            date(2026, 11, 24),
            100,
        )
        return [_price()]

    monkeypatch.setattr(tools, "get_stock_price_history", prices)

    result = await tools.get_price_history_data(
        object(), "comi.ca", "1mo", as_of_date=date(2026, 11, 24)
    )

    assert result["status"] == "available"
    assert result["payload"]["from_date"] == "2026-10-24"
    assert result["payload"]["prices"][0]["adj_close"] == "5.500000"


@pytest.mark.asyncio
async def test_snapshot_comparison_uses_one_ticker_and_both_requested_dates(monkeypatch) -> None:
    async def comparison(_session, ticker, first_date, second_date):
        assert ticker == "COMI.CA"
        assert (first_date, second_date) == (date(2026, 11, 16), date(2026, 11, 18))
        return _snapshot(date=first_date), _snapshot(date=second_date)

    async def calendar(_session, start_date, end_date):
        return _calendar(start_date, end_date)

    monkeypatch.setattr(tools, "repository_compare_snapshots", comparison)
    monkeypatch.setattr(tools, "get_verified_egx_calendar", calendar)

    result = await tools.compare_snapshots_data(
        object(), "comi.ca", date(2026, 11, 16), date(2026, 11, 18),
        as_of_date=date(2026, 11, 18),
    )

    assert result["status"] == "available"
    assert result["tickers"] == ["COMI.CA"]
    assert result["payload"]["first"]["date"] == "2026-11-16"
    assert result["payload"]["second"]["date"] == "2026-11-18"


def test_price_periods_and_row_limits_are_explicit() -> None:
    as_of = date(2026, 11, 24)

    assert tools._period_start("1w", as_of) == date(2026, 11, 17)
    assert tools._period_start("1mo", as_of) == date(2026, 10, 24)
    assert tools._period_start("3mo", as_of) == date(2026, 8, 24)
    assert tools._period_start("6mo", as_of) == date(2026, 5, 24)
    assert tools._period_start("1y", as_of) == date(2025, 11, 24)
    assert tools.DEFAULT_ROW_LIMIT == 100
    assert tools.MAX_ROW_LIMIT == 500
    with pytest.raises(ValueError, match="unsupported period"):
        tools._period_start("2y", as_of)


def test_glossary_tool_returns_definition_and_explicit_unknown_status() -> None:
    known = tools.get_indicator_glossary_data("RSI")
    unknown = tools.get_indicator_glossary_data("not an indicator")

    assert known["status"] == "available"
    assert known["definition"]["name"] == "RSI14"
    assert unknown["status"] == "not_found"


def test_tool_builder_exposes_exactly_the_five_read_only_tools() -> None:
    built = tools.build_stock_qa_tools(session=object())

    assert {tool.name for tool in built} == tools.ALLOWED_STOCK_QA_TOOLS
