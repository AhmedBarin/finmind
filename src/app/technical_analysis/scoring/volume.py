"""Volume-family scoring, with reliability decided upstream."""

import pandas as pd

from app.technical_analysis.config import (
    VOLUME_UNRELIABLE_IF_ZERO_SESSIONS,
    VOLUME_ZERO_CHECK_LOOKBACK_SESSIONS,
)
from app.technical_analysis.scoring.normalization import clip_score, require_finite
from app.technical_analysis.scoring.types import FamilyScore


def volume_is_reliable(recent_volume: pd.Series) -> bool:
    """Apply the configured 20-session zero-volume rule.

    The input must contain at least the configured number of recent sessions.
    Any zero in that window makes volume unreliable. Small positive values
    remain reliable because the agreed policy has no absolute volume floor.
    """
    values = recent_volume.astype("float64")
    lookback = VOLUME_ZERO_CHECK_LOOKBACK_SESSIONS
    if len(values) < lookback:
        raise ValueError(f"at least {lookback} recent volume sessions are required")
    window = values.iloc[-lookback:]
    if window.isna().any() or (window < 0).any():
        raise ValueError("recent volume values must be present and nonnegative")
    if VOLUME_UNRELIABLE_IF_ZERO_SESSIONS and (window == 0).any():
        return False
    return True


def volume_family_score(
    volume_ratio: float,
    daily_return_pct: float,
    atr_pct: float,
    *,
    volume_reliable: bool,
) -> FamilyScore:
    """Score volume confirmation; caller supplies the configured reliability result."""
    if not volume_reliable:
        return FamilyScore(
            score=None,
            indicator_scores={},
            reasons={"volume": "Unreliable: volume or liquidity quality gate failed."},
            reliable=False,
        )
    values = require_finite(
        volume_ratio=volume_ratio,
        daily_return_pct=daily_return_pct,
        atr_pct=atr_pct,
    )
    if values["volume_ratio"] < 0:
        raise ValueError("volume_ratio cannot be negative")
    if values["atr_pct"] <= 0:
        raise ValueError("ATR percent must be positive")

    intensity = min(1.0, max(0.0, (values["volume_ratio"] - 1.0) / 2.0))
    move_in_atr = values["daily_return_pct"] / values["atr_pct"]
    if move_in_atr > 0.25:
        direction = "up"
        score = 50.0 + 50.0 * intensity
    elif move_in_atr < -0.25:
        direction = "down"
        score = 50.0 - 50.0 * intensity
    else:
        direction = "neutral"
        score = 50.0
    components = {"volume": clip_score(score)}
    return FamilyScore(
        score=components["volume"],
        indicator_scores=components,
        reasons={
            "volume": (
                f"{direction} move ({move_in_atr:.3f} ATR) with volume intensity "
                f"{intensity:.3f}."
            )
        },
    )

