"""Trend-family scoring."""

from app.technical_analysis.config import TREND_COMPONENT_WEIGHTS
from app.technical_analysis.scoring.normalization import atr_gap_score, require_finite
from app.technical_analysis.scoring.types import FamilyScore


def trend_family_score(
    close: float,
    sma20: float,
    sma50: float,
    sma200: float,
    atr14: float,
) -> FamilyScore:
    """Score price/SMA alignment with the documented 30/30/40 weighting."""
    values = require_finite(close=close, sma20=sma20, sma50=sma50, sma200=sma200, atr14=atr14)
    components = {
        "close_vs_sma20": atr_gap_score(values["close"], values["sma20"], values["atr14"]),
        "sma20_vs_sma50": atr_gap_score(values["sma20"], values["sma50"], values["atr14"]),
        "sma50_vs_sma200": atr_gap_score(values["sma50"], values["sma200"], values["atr14"]),
    }
    total = sum(TREND_COMPONENT_WEIGHTS[key] * value for key, value in components.items())
    reasons = {
        key: f"ATR-normalized price gap score: {score:.2f}"
        for key, score in components.items()
    }
    return FamilyScore(score=total, indicator_scores=components, reasons=reasons)

