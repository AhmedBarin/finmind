"""Deterministic swing-pivot support and resistance levels."""

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class SupportResistance:
    support: float
    resistance: float
    support_touches: int
    resistance_touches: int
    breakout: bool
    breakdown: bool


def support_resistance(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    atr: float,
    volume_ratio: float,
    *,
    pivot_bars: int = 5,
    lookback: int = 120,
    cluster_atr: float = 0.5,
    fallback_periods: tuple[int, ...] = (20, 50),
) -> SupportResistance:
    """Find nearest pivot clusters around the latest close.

    Pivots require ``pivot_bars`` complete sessions on both sides. Clustering
    uses the current ATR as its distance scale. If no pivot exists on a side,
    the level falls back to the most recent configured rolling low/high.
    """
    _validate_inputs(high, low, close, atr, volume_ratio, pivot_bars, lookback, cluster_atr)
    if not fallback_periods or any(p < 1 for p in fallback_periods):
        raise ValueError("fallback_periods must contain positive periods")

    h, l, c = high.astype("float64"), low.astype("float64"), close.astype("float64")
    if len(c) == 0:
        raise ValueError("OHLC series cannot be empty")
    current_close = float(c.iloc[-1])
    latest_start = max(0, len(c) - lookback)
    # A centered 2*N+1 rolling window identifies a pivot only after its right
    # hand bars are known, avoiding look-ahead past the available history.
    window = 2 * pivot_bars + 1
    swing_high = h.eq(h.rolling(window, center=True, min_periods=window).max())
    swing_low = l.eq(l.rolling(window, center=True, min_periods=window).min())
    high_levels = h.iloc[latest_start:][swing_high.iloc[latest_start:]].dropna().tolist()
    low_levels = l.iloc[latest_start:][swing_low.iloc[latest_start:]].dropna().tolist()
    distance = atr * cluster_atr
    high_clusters = _cluster(high_levels, distance)
    low_clusters = _cluster(low_levels, distance)

    supports = [cluster for cluster in low_clusters if cluster[0] < current_close]
    resistances = [cluster for cluster in high_clusters if cluster[0] > current_close]
    fallback_low = min(float(l.tail(period).min()) for period in fallback_periods if len(l.tail(period)))
    fallback_high = max(float(h.tail(period).max()) for period in fallback_periods if len(h.tail(period)))
    support_cluster = max(supports, key=lambda cluster: cluster[0], default=(fallback_low, 0))
    resistance_cluster = min(resistances, key=lambda cluster: cluster[0], default=(fallback_high, 0))
    support, support_touches = support_cluster
    resistance, resistance_touches = resistance_cluster

    return SupportResistance(
        support=support,
        resistance=resistance,
        support_touches=support_touches,
        resistance_touches=resistance_touches,
        breakout=any(current_close > level + 0.25 * atr for level, _ in high_clusters)
        and volume_ratio > 1.5,
        breakdown=any(current_close < level - 0.25 * atr for level, _ in low_clusters),
    )


def _cluster(levels: list[float], distance: float) -> list[tuple[float, int]]:
    """Group sorted pivot prices and return mean level plus pivot count."""
    if not levels:
        return []
    ordered = sorted(levels)
    groups: list[list[float]] = [[ordered[0]]]
    for level in ordered[1:]:
        if level - groups[-1][-1] <= distance:
            groups[-1].append(level)
        else:
            groups.append([level])
    return [(sum(group) / len(group), len(group)) for group in groups]


def _validate_inputs(
    high: pd.Series,
    low: pd.Series,
    close: pd.Series,
    atr: float,
    volume_ratio: float,
    pivot_bars: int,
    lookback: int,
    cluster_atr: float,
) -> None:
    if not (high.index.equals(low.index) and low.index.equals(close.index)):
        raise ValueError("high, low, and close must have matching indexes")
    if atr <= 0:
        raise ValueError("atr must be positive")
    if volume_ratio < 0:
        raise ValueError("volume_ratio cannot be negative")
    if isinstance(pivot_bars, bool) or not isinstance(pivot_bars, int) or pivot_bars < 1:
        raise ValueError("pivot_bars must be a positive integer")
    if isinstance(lookback, bool) or not isinstance(lookback, int) or lookback < 1:
        raise ValueError("lookback must be a positive integer")
    if cluster_atr <= 0:
        raise ValueError("cluster_atr must be positive")

