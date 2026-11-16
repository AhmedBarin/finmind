"""Build user-facing recommendation payloads from deterministic decisions."""

from __future__ import annotations

import math

from app.recommendation.config import RECOMMENDATION_CONFIG_VERSION
from app.recommendation.decision import DecisionEvaluation
from app.recommendation.schemas import (
    ConfidenceLevel,
    FamilyResult,
    RecommendationDecision,
    RecommendationDataQuality,
    RecommendationFamilies,
    RecommendationInputs,
    RecommendationResult,
    UserFit,
    VolatilityResult,
)


_INDICATOR_FIELDS = (
    "close",
    "sma20",
    "sma50",
    "sma200",
    "rsi14",
    "macd",
    "macd_signal",
    "adx14",
    "volume_ratio",
    "support",
    "resistance",
)

_REASON_TEXT = {
    "trend": "Price and moving-average alignment need to improve.",
    "momentum": "Momentum needs to improve for a better entry.",
    "volume": "Volume confirmation is needed.",
    "support_resistance": "The price needs more room from resistance or a better support entry.",
    "volatility": "Volatility needs to fall within the profile's risk limit.",
    "extreme_volatility": "Volatility must fall below the extreme-risk level.",
    "liquidity_rank_unavailable": "A valid EGX liquidity rank is required.",
    "volatility_percentile_unavailable": "A valid volatility percentile is required.",
    "valid_snapshot_missing": "A valid technical snapshot is required.",
    "active_profile_missing": "A confirmed active investor profile is required.",
    "sector_unavailable": "Company sector data is required to apply your sector preferences.",
    "liquidity_below_profile_minimum": "The stock does not meet your profile's liquidity minimum.",
    "ticker_excluded": "The ticker is excluded by your investor profile.",
    "sector_restricted": "The sector is outside your investor profile preferences.",
    "trend_score_unavailable": "A trend score is required to evaluate this stock.",
    "momentum_score_unavailable": "A momentum score is required to evaluate this stock.",
    "support_resistance_score_unavailable": "A support/resistance score is required to evaluate this stock.",
    "bearish_technical_trigger": "A bearish technical condition was detected.",
}


def build_recommendation_result(
    inputs: RecommendationInputs,
    evaluation: DecisionEvaluation,
) -> RecommendationResult:
    """Map the decision and its evidence into the documented response shape."""
    snapshot = inputs.snapshot
    profile = inputs.profile
    indicators = snapshot.indicators if snapshot is not None else {}
    scores = snapshot.scores.get("family_scores", {}) if snapshot is not None else {}

    family_payload = {
        name: FamilyResult(
            score=gate.score,
            state=(scores.get(name) or {}).get("state"),
            min_required=gate.minimum,
            passed=gate.passed,
            reliable=gate.reliable,
        )
        for name, gate in evaluation.family_gates.items()
        if name != "volatility"
    }
    volatility_gate = evaluation.family_gates.get("volatility")
    volatility = VolatilityResult(
        atr_pct=_number_or_none(indicators.get("atr_pct")),
        percentile=volatility_gate.score if volatility_gate else None,
        label=snapshot.risk_label if snapshot is not None else None,
        cap=evaluation.atr_percentile_cap,
        passed=volatility_gate.passed if volatility_gate else None,
    )
    families = RecommendationFamilies(
        trend=family_payload.get("trend", FamilyResult()),
        momentum=family_payload.get("momentum", FamilyResult()),
        volume=family_payload.get("volume", FamilyResult()),
        support_resistance=family_payload.get(
            "support_resistance", FamilyResult()
        ),
        volatility=volatility,
    )

    reasons = list(evaluation.reasons)
    return RecommendationResult(
        ticker=inputs.ticker,
        trading_date=snapshot.date if snapshot is not None else None,
        snapshot_id=snapshot.id if snapshot is not None else None,
        config_version=RECOMMENDATION_CONFIG_VERSION,
        decision=evaluation.decision,
        reasons=reasons,
        watch_reasons=(
            [reason for reason in reasons if reason in _REASON_TEXT]
            if evaluation.decision.value == "WATCH"
            else []
        ),
        confidence=calculate_confidence(inputs, evaluation),
        setup_score=snapshot.setup_score if snapshot is not None else None,
        regime=snapshot.regime if snapshot is not None else None,
        families=families,
        indicators={
            key: _number_or_none(indicators.get(key)) for key in _INDICATOR_FIELDS
        },
        user_fit=(
            UserFit(
                risk_profile=profile.risk_profile.value,
                horizon=profile.investment_horizon.value,
                goal=profile.investment_goal.value,
            )
            if profile is not None
            else None
        ),
        rules={
            "fired": reasons,
            "filters_passed": list(evaluation.filters_passed),
        },
        what_would_change_it=[
            _REASON_TEXT[reason]
            for reason in reasons
            if reason in _REASON_TEXT
        ],
        data_quality=RecommendationDataQuality(
            price_status=(
                snapshot.data_quality_status if snapshot is not None else "unavailable"
            ),
            last_price_date=snapshot.date if snapshot is not None else None,
        ),
    )


def calculate_confidence(
    inputs: RecommendationInputs,
    evaluation: DecisionEvaluation,
) -> ConfidenceLevel:
    """Apply the spec's additive evidence and blocker confidence score."""
    snapshot = inputs.snapshot
    if snapshot is None or inputs.profile is None:
        return ConfidenceLevel.LOW
    if evaluation.decision in {
        RecommendationDecision.EXCLUDED,
        RecommendationDecision.NO_RECOMMENDATION,
    }:
        return ConfidenceLevel.LOW

    points = 0
    core_names = ("trend", "momentum", "volume", "support_resistance")
    strong_passes = sum(
        1
        for name in core_names
        if (gate := evaluation.family_gates.get(name)) is not None
        and gate.passed is True
        and gate.score is not None
        and gate.score - gate.minimum >= 10
    )
    if strong_passes >= 3:
        points += 1

    adx = _number_or_none(snapshot.indicators.get("adx14"))
    if adx is not None and (adx > 25 or adx < 20):
        points += 1

    volume_gate = evaluation.family_gates.get("volume")
    if (
        volume_gate is not None
        and volume_gate.reliable
        and volume_gate.score is not None
        and volume_gate.score >= 55
    ):
        points += 1

    if snapshot.data_quality_status == "valid" and not snapshot.quality_flags:
        points += 1

    volatility_gate = evaluation.family_gates.get("volatility")
    if (
        volatility_gate is not None
        and volatility_gate.score is not None
        and volatility_gate.minimum - volatility_gate.score >= 15
    ):
        points += 1

    failed_gates = sum(
        gate.passed is False for gate in evaluation.family_gates.values()
    )
    # A breakdown may produce AVOID without a failed numeric gate.
    if (
        evaluation.decision.value == "AVOID"
        and failed_gates == 0
        and "bearish_technical_trigger" in evaluation.reasons
    ):
        failed_gates = 1
    points -= failed_gates

    borderline_passes = sum(
        1
        for name in core_names
        if (gate := evaluation.family_gates.get(name)) is not None
        and gate.passed is True
        and gate.score is not None
        and 0 <= gate.score - gate.minimum <= 5
    )
    points -= borderline_passes

    if points >= 4:
        return ConfidenceLevel.HIGH
    if points >= 2:
        return ConfidenceLevel.MEDIUM
    return ConfidenceLevel.LOW


def _number_or_none(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
