"""Shared score normalization helpers."""

import math
from enum import Enum


class ScoreState(str, Enum):
    STRONGLY_BULLISH = "strongly_bullish"
    BULLISH = "bullish"
    NEUTRAL = "neutral"
    BEARISH = "bearish"
    STRONGLY_BEARISH = "strongly_bearish"


def clip_score(value: float) -> float:
    """Bound a score to the documented 0–100 range."""
    score = float(value)
    if not math.isfinite(score):
        raise ValueError("score must be finite")
    return min(100.0, max(0.0, score))


def score_state(value: float) -> ScoreState:
    """Map a bounded score to the source spec's descriptive score band."""
    score = float(value)
    if not math.isfinite(score) or not 0.0 <= score <= 100.0:
        raise ValueError("score state requires a finite score between 0 and 100")
    if score >= 80.0:
        return ScoreState.STRONGLY_BULLISH
    if score >= 65.0:
        return ScoreState.BULLISH
    if score >= 45.0:
        return ScoreState.NEUTRAL
    if score >= 25.0:
        return ScoreState.BEARISH
    return ScoreState.STRONGLY_BEARISH


def atr_gap_score(value_a: float, value_b: float, atr14: float) -> float:
    """Score the signed distance between two prices in ATR units.

    Zero ATR gap maps to 50, one positive ATR to 75, and one negative ATR to 25.
    """
    a, b, atr_value = float(value_a), float(value_b), float(atr14)
    if not all(math.isfinite(value) for value in (a, b, atr_value)):
        raise ValueError("price values and ATR14 must be finite")
    if atr_value <= 0:
        raise ValueError("ATR14 must be positive")
    return clip_score(50.0 + 25.0 * ((a - b) / atr_value))


def require_finite(**values: float) -> dict[str, float]:
    """Convert named values to floats and reject missing/non-finite inputs."""
    converted = {name: float(value) for name, value in values.items()}
    if not all(math.isfinite(value) for value in converted.values()):
        raise ValueError("scoring inputs must be finite numbers")
    return converted

