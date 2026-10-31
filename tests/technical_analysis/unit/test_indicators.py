import numpy as np
import pandas as pd

from app.technical_analysis.indicators import (
    adx,
    atr,
    atr_percent,
    average_traded_value,
    bollinger_bands,
    daily_return,
    macd,
    obv,
    rsi,
    rolling_percentile_rank,
    sma,
    true_range,
    volume_ratio,
    volume_sma,
)


def test_sma_waits_for_full_window() -> None:
    values = pd.Series([1.0, 2.0, 3.0, 4.0])
    result = sma(values, 3)
    assert result.iloc[:2].isna().all()
    assert result.iloc[2] == 2.0
    assert result.iloc[3] == 3.0


def test_rsi_handles_flat_prices_as_neutral() -> None:
    result = rsi(pd.Series([10.0] * 20), period=14)
    assert result.iloc[-1] == 50.0


def test_macd_returns_previous_histogram() -> None:
    result = macd(pd.Series(np.arange(1.0, 80.0)))
    assert result.columns.tolist() == ["macd", "macd_signal", "macd_hist", "macd_hist_prev"]
    assert result["macd_hist_prev"].iloc[-1] == result["macd_hist"].iloc[-2]


def test_true_range_uses_previous_close_gap() -> None:
    high = pd.Series([11.0, 13.0])
    low = pd.Series([9.0, 12.0])
    close = pd.Series([10.0, 12.5])
    result = true_range(high, low, close)
    assert result.tolist() == [2.0, 3.0]


def test_atr_and_adx_are_bounded_nonnegative() -> None:
    close = pd.Series(np.arange(10.0, 50.0))
    high, low = close + 1, close - 1
    atr_values = atr(high, low, close, period=14)
    adx_values = adx(high, low, close, period=14)
    assert atr_values.dropna().ge(0).all()
    assert adx_values["adx"].dropna().between(0, 100).all()


def test_bollinger_width_and_volume_calculations() -> None:
    close = pd.Series(np.arange(1.0, 25.0))
    bands = bollinger_bands(close, period=20)
    assert bands["bb_width"].iloc[-1] > 0

    volume = pd.Series([10.0, 20.0, 30.0, 40.0])
    average = volume_sma(volume, period=2)
    assert pd.isna(average.iloc[1])
    assert average.iloc[2] == 15.0  # prior two sessions only
    assert volume_ratio(volume, average).iloc[2] == 2.0
    assert np.isclose(daily_return(pd.Series([100.0, 110.0])).iloc[1], 0.1)


def test_percentile_rank_and_raw_traded_value() -> None:
    values = pd.Series(np.arange(1.0, 253.0))
    ranks = rolling_percentile_rank(values, period=252)
    assert pd.isna(ranks.iloc[-2])
    assert ranks.iloc[-1] == 100.0

    close = pd.Series([10.0, 20.0, 30.0])
    volume = pd.Series([2.0, 2.0, 2.0])
    assert average_traded_value(close, volume, period=2).iloc[-1] == 50.0
    assert atr_percent(pd.Series([2.0]), pd.Series([40.0])).iloc[0] == 5.0


def test_obv_adds_and_subtracts_volume_by_close_direction() -> None:
    close = pd.Series([10.0, 11.0, 9.0, 9.0])
    volume = pd.Series([100.0, 20.0, 30.0, 40.0])
    assert obv(close, volume).tolist() == [0.0, 20.0, -10.0, -10.0]


def test_support_resistance_uses_fallbacks_when_no_pivots() -> None:
    from app.technical_analysis.indicators import support_resistance

    close = pd.Series([10.0, 10.5, 10.25, 10.75])
    high, low = close + 0.5, close - 0.5
    result = support_resistance(
        high, low, close, atr=1.0, volume_ratio=1.0, pivot_bars=5
    )
    assert result.support == low.min()
    assert result.resistance == high.max()
    assert result.support_touches == result.resistance_touches == 0

