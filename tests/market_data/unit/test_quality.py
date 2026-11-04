import pandas as pd
import pytest

from app.market_data.quality import DataQualityStatus, inspect_price_history


def _prices(dates: list[str]) -> pd.DataFrame:
    count = len(dates)
    close = [100.0 + i for i in range(count)]
    return pd.DataFrame(
        {
            "Date": pd.to_datetime(dates),
            "Open": close,
            "High": [value + 1 for value in close],
            "Low": [value - 1 for value in close],
            "Close": close,
            "Adj Close": close,
            "Volume": [100.0] * count,
            "Dividends": [0.0] * count,
            "Stock Splits": [0.0] * count,
        }
    )


def test_history_readiness_keeps_sma_and_percentile_needs_separate() -> None:
    prices = _prices(pd.date_range("2024-01-01", periods=220).astype(str).tolist())
    result = inspect_price_history(
        prices,
        as_of_date=prices["Date"].iloc[-1],
        expected_trading_sessions=prices["Date"],
    )
    assert result.session_count == 220
    assert not result.insufficient_history
    assert not result.percentile_history_ready
    assert result.status is DataQualityStatus.VALID
    assert "limited_percentile_history" in result.flags


def test_duplicate_and_out_of_order_dates_are_reported_without_mutation() -> None:
    prices = _prices(["2024-01-02", "2024-01-01", "2024-01-02"])
    original = prices.copy(deep=True)
    result = inspect_price_history(prices)
    assert result.out_of_order
    assert result.duplicate_dates == (pd.Timestamp("2024-01-02"),)
    pd.testing.assert_frame_equal(prices, original)


def test_expected_calendar_sessions_report_gaps() -> None:
    prices = _prices(["2024-01-01", "2024-01-03"])
    result = inspect_price_history(
        prices,
        expected_trading_sessions=pd.date_range("2024-01-01", "2024-01-03"),
    )
    assert result.missing_sessions == (pd.Timestamp("2024-01-02"),)


def test_zero_volume_check_uses_latest_20_rows() -> None:
    dates = pd.date_range("2024-01-01", periods=21).astype(str).tolist()
    prices = _prices(dates)
    prices.loc[0, "Volume"] = 0.0
    prices.loc[1, "Volume"] = 0.0
    prices.loc[20, "Volume"] = 0.0
    result = inspect_price_history(prices)
    assert result.zero_volume_dates == (
        pd.Timestamp("2024-01-02"),
        pd.Timestamp("2024-01-21"),
    )


def test_stale_check_is_injected_as_trading_sessions() -> None:
    prices = _prices(["2024-01-01"])
    assert inspect_price_history(prices).stale is None
    assert not inspect_price_history(prices, as_of_date="2024-01-02").stale
    assert inspect_price_history(prices, as_of_date="2024-01-03").stale


def test_price_jumps_use_threshold_and_ignore_recorded_actions() -> None:
    prices = _prices(["2024-01-01", "2024-01-02", "2024-01-03"])
    prices["Close"] = [100.0, 150.0, 75.0]
    prices["Adj Close"] = prices["Close"]
    prices.loc[2, "Stock Splits"] = 2.0
    result = inspect_price_history(prices, max_abs_price_change=0.20)
    assert len(result.unexplained_price_jumps) == 1
    assert result.unexplained_price_jumps[0].date == pd.Timestamp("2024-01-02")
    assert result.unexplained_price_jumps[0].return_fraction == 0.5


def test_unresolved_checks_remain_explicitly_unassessed() -> None:
    result = inspect_price_history(_prices(["2024-01-01"]))
    assert result.missing_sessions == ()
    assert result.stale is None
    assert result.unexplained_price_jumps == ()
    assert result.status is None


def test_zero_volume_only_makes_volume_unreliable_not_overall_data_flagged() -> None:
    dates = pd.date_range("2024-01-01", periods=200).astype(str).tolist()
    prices = _prices(dates)
    prices.loc[199, "Volume"] = 0
    result = inspect_price_history(
        prices,
        as_of_date=prices["Date"].iloc[-1],
        expected_trading_sessions=pd.to_datetime(dates),
    )
    assert result.status is DataQualityStatus.VALID
    assert not result.volume_reliable
    assert "zero_volume_sessions" in result.flags


def test_status_prioritizes_insufficient_history_then_stale_then_flags() -> None:
    short = _prices(pd.date_range("2024-01-01", periods=30).astype(str).tolist())
    assert (
        inspect_price_history(short, as_of_date=short["Date"].iloc[-1]).status
        is DataQualityStatus.INSUFFICIENT_HISTORY
    )

    long = _prices(pd.date_range("2024-01-01", periods=210).astype(str).tolist())
    stale = inspect_price_history(long, as_of_date="2024-11-01")
    assert stale.status is DataQualityStatus.STALE

    expected = pd.date_range("2024-01-01", periods=201)
    flagged_prices = _prices(expected.astype(str).tolist()).drop(index=100)
    flagged = inspect_price_history(
        flagged_prices,
        as_of_date=expected[-1],
        expected_trading_sessions=expected,
    )
    assert flagged.status is DataQualityStatus.FLAGGED
    assert flagged.missing_sessions == (expected[100],)


def test_invalid_settings_and_missing_columns_are_rejected() -> None:
    with pytest.raises(ValueError, match="positive integers"):
        inspect_price_history(_prices(["2024-01-01"]), minimum_history=0)
    with pytest.raises(ValueError, match="missing columns"):
        inspect_price_history(_prices(["2024-01-01"]).drop(columns="Volume"))
