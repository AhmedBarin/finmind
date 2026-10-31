"""Volatility indicators: True Range, ATR, and Bollinger Bands."""

import pandas as pd

from app.technical_analysis.indicators.momentum import _wilder_mean


def true_range(high: pd.Series, low: pd.Series, close: pd.Series) -> pd.Series:
    """Return max(H-L, abs(H-prev close), abs(L-prev close))."""
    _validate_ohlc(high, low, close)
    previous_close = close.astype("float64").shift(1)
    ranges = pd.concat(
        [high.astype("float64") - low.astype("float64"),
         (high.astype("float64") - previous_close).abs(),
         (low.astype("float64") - previous_close).abs()],
        axis=1,
    )
    return ranges.max(axis=1, skipna=True)


def atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """Return ATR using Wilder smoothing of True Range."""
    _validate_period(period)
    return _wilder_mean(true_range(high, low, close), period)


def bollinger_bands(
    close: pd.Series, period: int = 20, deviations: float = 2.0
) -> pd.DataFrame:
    """Return middle, upper, lower bands, and width (fraction, not percent)."""
    _validate_period(period)
    if deviations <= 0:
        raise ValueError("deviations must be positive")
    prices = close.astype("float64")
    middle = prices.rolling(period, min_periods=period).mean()
    std = prices.rolling(period, min_periods=period).std(ddof=0)
    upper = middle + deviations * std
    lower = middle - deviations * std
    width = (upper - lower) / middle.where(middle != 0)
    return pd.DataFrame(
        {"bb_middle": middle, "bb_upper": upper, "bb_lower": lower, "bb_width": width},
        index=prices.index,
    )


def atr_percent(atr_values: pd.Series, close: pd.Series) -> pd.Series:
    """Return ATR as a percentage of close."""
    return atr_values.astype("float64").div(close.astype("float64")).mul(100.0)


def _validate_ohlc(high: pd.Series, low: pd.Series, close: pd.Series) -> None:
    if not (high.index.equals(low.index) and low.index.equals(close.index)):
        raise ValueError("high, low, and close must have matching indexes")


def _validate_period(period: int) -> None:
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError("period must be a positive integer")

