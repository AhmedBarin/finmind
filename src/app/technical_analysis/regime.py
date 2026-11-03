"""Market-regime classification from ADX with hysteresis."""

from enum import Enum
import math

from app.technical_analysis.config import RegimeThresholds


class Regime(str, Enum):
    TRENDING = "trending"
    TRANSITION = "transition"
    RANGING = "ranging"


def classify_regime(
    adx14: float | None,
    previous_regime: Regime | str | None = None,
    thresholds: RegimeThresholds = RegimeThresholds(),
) -> Regime | None:
    """Classify ADX14, retaining the previous state inside hysteresis bands.

    With no prior regime, the source spec's baseline boundaries apply:
    ADX > 25 trending, ADX < 20 ranging, and values between them transition.
    """
    if adx14 is None or (isinstance(adx14, float) and math.isnan(adx14)):
        return None
    value = float(adx14)
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("ADX14 must be a finite value between 0 and 100")
    previous = Regime(previous_regime) if previous_regime is not None else None

    if previous is Regime.TRENDING and value >= thresholds.trending_exit:
        return Regime.TRENDING
    if previous is Regime.RANGING and value <= thresholds.ranging_exit:
        return Regime.RANGING
    if previous is None:
        if value > 25:
            return Regime.TRENDING
        if value < 20:
            return Regime.RANGING
        return Regime.TRANSITION
    if value >= thresholds.trending_enter:
        return Regime.TRENDING
    if value <= thresholds.ranging_enter:
        return Regime.RANGING
    return Regime.TRANSITION

