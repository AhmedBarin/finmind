"""Volatility risk classification from ATR% historical percentile."""

from enum import Enum
import math

from app.technical_analysis.config import RiskThresholds


class RiskLabel(str, Enum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    VERY_HIGH = "very_high"


def classify_risk(
    atr_pct_percentile: float | None,
    thresholds: RiskThresholds = RiskThresholds(),
) -> RiskLabel | None:
    """Map ATR% percentile to a risk label, without adding a bullish bonus.

    Buckets are lower-inclusive and upper-exclusive; exactly 90 is very high.
    """
    if atr_pct_percentile is None or (
        isinstance(atr_pct_percentile, float) and math.isnan(atr_pct_percentile)
    ):
        return None
    value = float(atr_pct_percentile)
    if not math.isfinite(value) or not 0 <= value <= 100:
        raise ValueError("ATR% percentile must be a finite value between 0 and 100")
    if value < thresholds.low_max:
        return RiskLabel.LOW
    if value < thresholds.medium_max:
        return RiskLabel.MEDIUM
    if value < thresholds.high_max:
        return RiskLabel.HIGH
    return RiskLabel.VERY_HIGH

