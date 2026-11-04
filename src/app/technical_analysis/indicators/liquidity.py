"""Per-ticker liquidity indicators."""

import pandas as pd


def average_traded_value(
    raw_close: pd.Series, volume: pd.Series, period: int = 20
) -> pd.Series:
    """Return rolling mean of raw close times volume, aligned to the input.

    Liquidity intentionally uses unadjusted/raw close, as specified by the
    market-data decision. Unlike volume SMA, the current session is included.
    """
    if not raw_close.index.equals(volume.index):
        raise ValueError("raw_close and volume must have matching indexes")
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError("period must be a positive integer")
    traded_value = raw_close.astype("float64") * volume.astype("float64")
    return traded_value.rolling(period, min_periods=period).mean()

