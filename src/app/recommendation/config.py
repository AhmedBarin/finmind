"""Documented Recommendation Engine decision thresholds."""

from __future__ import annotations

from dataclasses import dataclass

from app.investor.schemas import InvestmentHorizon, RiskProfile


RECOMMENDATION_CONFIG_VERSION = "recommendation-v1"
EXTREME_ATR_PERCENTILE = 95.0


@dataclass(frozen=True)
class FamilyMinimums:
    trend: float
    momentum: float
    volume: float
    support_resistance: float


# Baseline minimums for a medium investment horizon, copied from the unified spec.
BASELINE_MINIMUMS: dict[RiskProfile, FamilyMinimums] = {
    RiskProfile.CONSERVATIVE: FamilyMinimums(70, 55, 50, 45),
    RiskProfile.MODERATE: FamilyMinimums(65, 50, 45, 40),
    RiskProfile.AGGRESSIVE: FamilyMinimums(60, 45, 40, 35),
}

# Horizon adjustments are added to medium-horizon minimums, then clamped to 0–100.
HORIZON_ADJUSTMENTS: dict[InvestmentHorizon, FamilyMinimums] = {
    InvestmentHorizon.SHORT: FamilyMinimums(-5, 10, 5, 5),
    InvestmentHorizon.MEDIUM: FamilyMinimums(0, 0, 0, 0),
    InvestmentHorizon.LONG: FamilyMinimums(5, -10, -10, -10),
}


def family_minimums(
    risk_profile: RiskProfile,
    horizon: InvestmentHorizon,
) -> FamilyMinimums:
    """Return the spec's risk- and horizon-adjusted family score minimums."""
    base = BASELINE_MINIMUMS[risk_profile]
    adjustment = HORIZON_ADJUSTMENTS[horizon]
    return FamilyMinimums(
        trend=_clamp(base.trend + adjustment.trend),
        momentum=_clamp(base.momentum + adjustment.momentum),
        volume=_clamp(base.volume + adjustment.volume),
        support_resistance=_clamp(
            base.support_resistance + adjustment.support_resistance
        ),
    )


def _clamp(value: float) -> float:
    return min(100.0, max(0.0, float(value)))
