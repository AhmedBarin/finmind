"""Historical context helpers for volatility indicators."""

import pandas as pd


def rolling_percentile_rank(values: pd.Series, period: int = 252) -> pd.Series:
    """Rank each value against its trailing window, expressed from 0 to 100.

    The current observation is included. A result is emitted only after a full
    window is available; ties use the inclusive empirical rank (``<=``).
    """
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError("period must be a positive integer")
    series = values.astype("float64")
    return series.rolling(period, min_periods=period).apply(
        lambda window: 100.0 * (window <= window[-1]).sum() / len(window),
        raw=True,
    )

