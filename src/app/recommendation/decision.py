"""Deterministic Recommendation Engine filters and decision gates."""

from __future__ import annotations

from dataclasses import dataclass
import math

from app.recommendation.config import (
    EXTREME_ATR_PERCENTILE,
    family_minimums,
)
from app.recommendation.schemas import RecommendationDecision, RecommendationInputs


@dataclass(frozen=True)
class FamilyGate:
    score: float | None
    minimum: float
    passed: bool | None
    reliable: bool


@dataclass(frozen=True)
class DecisionEvaluation:
    decision: RecommendationDecision
    reasons: tuple[str, ...]
    filters_passed: tuple[str, ...]
    family_gates: dict[str, FamilyGate]
    liquidity_rank_minimum: float | None
    atr_percentile_cap: float | None


def evaluate_decision(
    inputs: RecommendationInputs,
) -> DecisionEvaluation:
    """Apply suitability filters and technical BUY gates to loaded inputs.

    A missing liquidity percentile or volatility percentile blocks evaluation
    safely; it is never assumed to pass. News is not an input in this version.
    """
    profile = inputs.profile
    snapshot = inputs.snapshot
    if profile is None:
        return _no_recommendation("active_profile_missing")
    if snapshot is None:
        return _no_recommendation("valid_snapshot_missing")

    indicators = snapshot.indicators
    family_scores = snapshot.scores.get("family_scores", {})
    filters_passed: list[str] = ["data_quality"]

    if _ticker_is_excluded(inputs.ticker, profile.excluded_tickers):
        return _excluded("ticker_excluded", filters_passed)

    sector_result = _sector_restriction(inputs.sector, profile)
    if sector_result == "missing":
        return _no_recommendation("sector_unavailable")
    if sector_result == "excluded":
        return _excluded("sector_restricted", filters_passed)
    filters_passed.append("user_restrictions")

    rank_minimum = float(profile.liquidity_floor_pct)
    liquidity_rank = _finite_or_none(inputs.liquidity_rank_pct)
    if liquidity_rank is None:
        return _no_recommendation(
            "liquidity_rank_unavailable",
            filters_passed=filters_passed,
            rank_minimum=rank_minimum,
            atr_cap=float(profile.max_atr_pctl_cap),
        )
    if liquidity_rank < rank_minimum:
        return _excluded(
            "liquidity_below_profile_minimum",
            filters_passed,
            rank_minimum=rank_minimum,
            atr_cap=float(profile.max_atr_pctl_cap),
        )
    filters_passed.append("liquidity")

    atr_percentile = _finite_or_none(indicators.get("atr_pct_percentile_1y"))
    if atr_percentile is None:
        return _no_recommendation(
            "volatility_percentile_unavailable",
            filters_passed=filters_passed,
            rank_minimum=rank_minimum,
            atr_cap=float(profile.max_atr_pctl_cap),
        )

    mins = family_minimums(profile.risk_profile, profile.investment_horizon)
    required = {
        "trend": mins.trend,
        "momentum": mins.momentum,
        "volume": mins.volume,
        "support_resistance": mins.support_resistance,
    }
    gates: dict[str, FamilyGate] = {}
    for name, minimum in required.items():
        family = family_scores.get(name) or {}
        score = _finite_or_none(family.get("score"))
        reliable = bool(family.get("reliable", name != "volume"))
        if name == "volume" and not reliable:
            gates[name] = FamilyGate(score, minimum, None, False)
        elif score is None:
            return _no_recommendation(
                f"{name}_score_unavailable",
                filters_passed=filters_passed,
                gates=gates,
                rank_minimum=rank_minimum,
                atr_cap=float(profile.max_atr_pctl_cap),
            )
        else:
            gates[name] = FamilyGate(score, minimum, score >= minimum, reliable)

    atr_cap = float(profile.max_atr_pctl_cap)
    atr_passed = atr_percentile <= atr_cap
    gates["volatility"] = FamilyGate(
        score=atr_percentile,
        minimum=atr_cap,
        passed=atr_passed,
        reliable=True,
    )

    blockers = [
        name
        for name, gate in gates.items()
        if gate.passed is False
    ]
    breakdown = bool(indicators.get("breakdown", False))
    trend_score = gates["trend"].score
    momentum_score = gates["momentum"].score
    volume_score = gates["volume"].score
    volume_reliable = gates["volume"].reliable
    avoid = (
        (trend_score is not None and trend_score < 40)
        or breakdown
        or (
            momentum_score is not None
            and momentum_score < 30
            and volume_reliable
            and volume_score is not None
            and volume_score < 40
        )
    )

    if avoid:
        decision = RecommendationDecision.AVOID
        reasons = ["bearish_technical_trigger", *blockers]
    elif atr_percentile > EXTREME_ATR_PERCENTILE:
        decision = RecommendationDecision.WATCH
        reasons = ["extreme_volatility", *blockers]
    elif blockers:
        decision = RecommendationDecision.WATCH
        reasons = blockers
    else:
        decision = RecommendationDecision.BUY
        reasons = []

    return DecisionEvaluation(
        decision=decision,
        reasons=tuple(dict.fromkeys(reasons)),
        filters_passed=tuple(filters_passed),
        family_gates=gates,
        liquidity_rank_minimum=rank_minimum,
        atr_percentile_cap=atr_cap,
    )


def _ticker_is_excluded(ticker: str, excluded: list[str]) -> bool:
    normalized = ticker.strip().upper()
    base_ticker = normalized.removesuffix(".CA")
    excluded_values = {value.strip().upper() for value in excluded}
    return normalized in excluded_values or base_ticker in excluded_values


def _sector_restriction(sector: str | None, profile) -> str:
    excluded = {value.strip().casefold() for value in profile.excluded_sectors}
    preferred = {value.strip().casefold() for value in profile.preferred_sectors}
    if not excluded and not preferred:
        return "pass"
    if sector is None or not sector.strip():
        return "missing"
    normalized_sector = sector.strip().casefold()
    if normalized_sector in excluded:
        return "excluded"
    if preferred and normalized_sector not in preferred:
        return "excluded"
    return "pass"


def _finite_or_none(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        converted = float(value)
    except (TypeError, ValueError):
        return None
    return converted if math.isfinite(converted) else None


def _no_recommendation(
    reason: str,
    *,
    filters_passed: list[str] | None = None,
    gates: dict[str, FamilyGate] | None = None,
    rank_minimum: float | None = None,
    atr_cap: float | None = None,
) -> DecisionEvaluation:
    return DecisionEvaluation(
        decision=RecommendationDecision.NO_RECOMMENDATION,
        reasons=(reason,),
        filters_passed=tuple(filters_passed or ()),
        family_gates=gates or {},
        liquidity_rank_minimum=rank_minimum,
        atr_percentile_cap=atr_cap,
    )


def _excluded(
    reason: str,
    filters_passed: list[str],
    *,
    rank_minimum: float | None = None,
    atr_cap: float | None = None,
) -> DecisionEvaluation:
    return DecisionEvaluation(
        decision=RecommendationDecision.EXCLUDED,
        reasons=(reason,),
        filters_passed=tuple(filters_passed),
        family_gates={},
        liquidity_rank_minimum=rank_minimum,
        atr_percentile_cap=atr_cap,
    )
