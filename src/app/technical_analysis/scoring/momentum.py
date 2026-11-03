"""Momentum-family scoring from regime-aware RSI and MACD histogram."""

from collections.abc import Sequence

from app.technical_analysis.config import MOMENTUM_COMPONENT_WEIGHTS, RSI_ANCHORS
from app.technical_analysis.regime import Regime
from app.technical_analysis.scoring.normalization import clip_score, require_finite
from app.technical_analysis.scoring.types import FamilyScore


def rsi_score(rsi14: float, regime: Regime | str) -> float:
    """Linearly interpolate the spec's RSI table for the selected regime."""
    value = require_finite(rsi14=rsi14)["rsi14"]
    if not 0 <= value <= 100:
        raise ValueError("RSI14 must be between 0 and 100")
    current_regime = Regime(regime)
    trending = _interpolate(value, RSI_ANCHORS[Regime.TRENDING.value])
    ranging = _interpolate(value, RSI_ANCHORS[Regime.RANGING.value])
    if current_regime is Regime.TRENDING:
        return trending
    if current_regime is Regime.RANGING:
        return ranging
    return (trending + ranging) / 2.0


def macd_histogram_score(macd_hist: float, macd_hist_prev: float) -> float:
    """Score MACD histogram direction and whether its momentum is rising."""
    values = require_finite(macd_hist=macd_hist, macd_hist_prev=macd_hist_prev)
    current, previous = values["macd_hist"], values["macd_hist_prev"]
    if current == 0 or current == previous:
        return 50.0  # Neutral convention for a zero or unchanged histogram.
    above_signal = current > 0
    histogram_rising = current > previous
    if above_signal:
        return 85.0 if histogram_rising else 65.0
    return 35.0 if histogram_rising else 15.0


def momentum_family_score(
    rsi14: float,
    macd_hist: float,
    macd_hist_prev: float,
    regime: Regime | str,
) -> FamilyScore:
    """Combine the regime-aware RSI and MACD scores equally."""
    rsi_component = rsi_score(rsi14, regime)
    macd_component = macd_histogram_score(macd_hist, macd_hist_prev)
    components = {"rsi14": rsi_component, "macd_histogram": macd_component}
    return FamilyScore(
        score=(
            MOMENTUM_COMPONENT_WEIGHTS["rsi14"] * rsi_component
            + MOMENTUM_COMPONENT_WEIGHTS["macd_histogram"] * macd_component
        ),
        indicator_scores=components,
        reasons={
            "rsi14": f"Regime-aware RSI score for {Regime(regime).value} regime: {rsi_component:.2f}",
            "macd_histogram": f"Histogram direction/momentum score: {macd_component:.2f}",
        },
    )


def _interpolate(value: float, anchors: Sequence[tuple[float, float]]) -> float:
    if value <= anchors[0][0]:
        return anchors[0][1]
    if value >= anchors[-1][0]:
        return anchors[-1][1]
    for (x0, y0), (x1, y1) in zip(anchors, anchors[1:]):
        if x0 <= value <= x1:
            portion = (value - x0) / (x1 - x0)
            return clip_score(y0 + portion * (y1 - y0))
    raise RuntimeError("RSI interpolation failed for an in-range value")

