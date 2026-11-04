"""Moving average indicators."""

import pandas as pd


def sma(values: pd.Series, period: int) -> pd.Series:
    """Return the simple moving average, aligned to the input index."""
    _validate_period(period)
    return values.astype("float64").rolling(window=period, min_periods=period).mean()


def ema(values: pd.Series, period: int) -> pd.Series:
    """Return an exponentially weighted moving average with an initial warm-up."""
    _validate_period(period)
    series = values.astype("float64")
    # Seed with the first full-period SMA, then apply the standard EMA recurrence.
    result = pd.Series(float("nan"), index=series.index, dtype="float64")
    if len(series) < period:
        return result
    first = series.rolling(period, min_periods=period).mean()
    valid = first.first_valid_index()
    if valid is None:
        return result
    start = series.index.get_loc(valid)
    result.iloc[start] = first.iloc[start]
    alpha = 2.0 / (period + 1.0)
    for i in range(start + 1, len(series)):
        if pd.isna(series.iloc[i]) or pd.isna(result.iloc[i - 1]):
            continue
        result.iloc[i] = alpha * series.iloc[i] + (1.0 - alpha) * result.iloc[i - 1]
    return result


def _validate_period(period: int) -> None:
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError("period must be a positive integer")

