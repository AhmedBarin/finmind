"""Support/resistance family scoring."""

from app.technical_analysis.scoring.normalization import clip_score, require_finite
from app.technical_analysis.scoring.types import FamilyScore


def support_resistance_score(
    close: float,
    support: float,
    resistance: float,
    atr14: float,
    *,
    breakout: bool,
    breakdown: bool,
) -> FamilyScore:
    """Apply the spec's support/resistance adjustments and clip to 0–100."""
    values = require_finite(close=close, support=support, resistance=resistance, atr14=atr14)
    if values["atr14"] <= 0:
        raise ValueError("ATR14 must be positive")
    ds = (values["close"] - values["support"]) / values["atr14"]
    dr = (values["resistance"] - values["close"]) / values["atr14"]
    adjustments: list[str] = []
    score = 50.0
    if ds < 1.0 and not breakdown:
        score += 15.0
        adjustments.append("near support +15")
    if dr < 1.0 and not breakout:
        score -= 15.0
        adjustments.append("near resistance -15")
    if breakout:
        score += 30.0
        adjustments.append("breakout +30")
    if breakdown:
        score -= 30.0
        adjustments.append("breakdown -30")
    if dr > 3.0:
        score += 10.0
        adjustments.append("more than 3 ATR to resistance +10")
    final_score = clip_score(score)
    return FamilyScore(
        score=final_score,
        indicator_scores={"support_resistance": final_score},
        reasons={
            "support_resistance": ", ".join(adjustments) if adjustments else "No adjustment; neutral baseline."
        },
    )
