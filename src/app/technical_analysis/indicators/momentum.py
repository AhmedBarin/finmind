"""Momentum indicators: RSI and MACD."""

import pandas as pd

from app.technical_analysis.indicators.moving_average import ema


def rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """Calculate RSI using Wilder-smoothed average gains and losses."""
    _validate_period(period)
    prices = close.astype("float64")
    change = prices.diff()
    gains = change.clip(lower=0.0)
    losses = -change.clip(upper=0.0)
    avg_gain = _wilder_mean(gains, period)
    avg_loss = _wilder_mean(losses, period)
    rs = avg_gain / avg_loss
    result = 100.0 - (100.0 / (1.0 + rs))
    result = result.mask((avg_loss == 0) & (avg_gain > 0), 100.0)
    result = result.mask((avg_loss == 0) & (avg_gain == 0), 50.0)
    return result.clip(0.0, 100.0)


def macd(
    close: pd.Series,
    fast_period: int = 12,
    slow_period: int = 26,
    signal_period: int = 9,
) -> pd.DataFrame:
    """Return MACD line, signal, histogram, and prior histogram columns."""
    for period in (fast_period, slow_period, signal_period):
        _validate_period(period)
    if fast_period >= slow_period:
        raise ValueError("fast_period must be less than slow_period")
    prices = close.astype("float64")
    line = ema(prices, fast_period) - ema(prices, slow_period)
    signal = ema(line, signal_period)
    histogram = line - signal
    return pd.DataFrame(
        {"macd": line, "macd_signal": signal, "macd_hist": histogram, "macd_hist_prev": histogram.shift(1)},
        index=prices.index,
    )


def _wilder_mean(values: pd.Series, period: int) -> pd.Series:
    """Wilder smoothing seeded by the first full-period arithmetic mean."""
    result = pd.Series(float("nan"), index=values.index, dtype="float64")
    if len(values) < period:
        return result
    seed = values.rolling(period, min_periods=period).mean()
    first = seed.first_valid_index()
    if first is None:
        return result
    start = values.index.get_loc(first)
    result.iloc[start] = seed.iloc[start]
    for i in range(start + 1, len(values)):
        if pd.isna(values.iloc[i]) or pd.isna(result.iloc[i - 1]):
            continue
        result.iloc[i] = (result.iloc[i - 1] * (period - 1) + values.iloc[i]) / period
    return result


def _validate_period(period: int) -> None:
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError("period must be a positive integer")

