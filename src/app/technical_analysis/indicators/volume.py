"""Volume and price-change context indicators."""

import pandas as pd


def volume_sma(volume: pd.Series, period: int = 20, *, exclude_today: bool = True) -> pd.Series:
    """Return rolling average volume; by default, today's bar is excluded."""
    _validate_period(period)
    values = volume.astype("float64")
    if exclude_today:
        values = values.shift(1)
    return values.rolling(period, min_periods=period).mean()


def volume_ratio(volume: pd.Series, average_volume: pd.Series) -> pd.Series:
    """Return current volume divided by the supplied average volume."""
    if not volume.index.equals(average_volume.index):
        raise ValueError("volume and average_volume must have matching indexes")
    denominator = average_volume.astype("float64").where(average_volume != 0)
    return volume.astype("float64").div(denominator)


def daily_return(close: pd.Series, *, percent: bool = False) -> pd.Series:
    """Return close-to-close return as a fraction, or percent when requested."""
    result = close.astype("float64").pct_change(fill_method=None)
    return result * 100.0 if percent else result


def obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """Return On-Balance Volume as a cumulative signed volume series.

    OBV is provided as an optional raw indicator only; the scoring layer must
    decide whether it is enabled and how its slope is normalized.
    """
    if not close.index.equals(volume.index):
        raise ValueError("close and volume must have matching indexes")
    if close.empty:
        return pd.Series(index=close.index, dtype="float64")
    direction = close.astype("float64").diff().map(
        lambda change: 1.0 if change > 0 else -1.0 if change < 0 else 0.0
    )
    direction.iloc[0] = 0.0
    signed_volume = direction * volume.astype("float64")
    return signed_volume.cumsum()


def _validate_period(period: int) -> None:
    if isinstance(period, bool) or not isinstance(period, int) or period < 1:
        raise ValueError("period must be a positive integer")

