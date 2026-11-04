"""Trend-strength indicators."""

import pandas as pd

from app.technical_analysis.indicators.momentum import _wilder_mean
from app.technical_analysis.indicators.volatility import true_range


def adx(
    high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14
) -> pd.DataFrame:
    """Return +DI, -DI, DX, and ADX using Wilder smoothing."""
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError("period must be a positive integer")
    if not (high.index.equals(low.index) and low.index.equals(close.index)):
        raise ValueError("high, low, and close must have matching indexes")
    h, l = high.astype("float64"), low.astype("float64")
    up_move = h.diff()
    down_move = -l.diff()
    plus_dm = up_move.where((up_move > down_move) & (up_move > 0), 0.0)
    minus_dm = down_move.where((down_move > up_move) & (down_move > 0), 0.0)
    tr = true_range(h, l, close.astype("float64"))
    smoothed_tr = _wilder_mean(tr, period)
    plus_di = 100.0 * _wilder_mean(plus_dm, period).div(smoothed_tr.where(smoothed_tr != 0))
    minus_di = 100.0 * _wilder_mean(minus_dm, period).div(smoothed_tr.where(smoothed_tr != 0))
    denominator = (plus_di + minus_di).where((plus_di + minus_di) != 0)
    dx = 100.0 * (plus_di - minus_di).abs().div(denominator)
    dx = dx.mask((plus_di == 0) & (minus_di == 0), 0.0)
    adx_values = _wilder_mean(dx, period)
    return pd.DataFrame({"plus_di": plus_di, "minus_di": minus_di, "dx": dx, "adx": adx_values}, index=h.index)

