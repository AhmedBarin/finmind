from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest

from app.investor.schemas import (
    InvestmentExperience,
    InvestmentGoal,
    InvestmentHorizon,
    InvestorProfilePayload,
    RiskProfile,
)
from app.recommendation.config import family_minimums
from app.recommendation.decision import evaluate_decision
from app.recommendation.schemas import RecommendationDecision, RecommendationInputs


def _inputs(
    *,
    risk: RiskProfile = RiskProfile.MODERATE,
    horizon: InvestmentHorizon = InvestmentHorizon.MEDIUM,
    excluded_tickers: list[str] | None = None,
    excluded_sectors: list[str] | None = None,
    preferred_sectors: list[str] | None = None,
    sector: str | None = "Financial Services",
    liquidity_rank_pct: float | None = 70,
    status: str = "valid",
    indicators: dict[str, object] | None = None,
    family_scores: dict[str, dict[str, object]] | None = None,
) -> RecommendationInputs:
    user_id = uuid4()
    profile = InvestorProfilePayload(
        user_id=user_id,
        risk_profile=risk,
        investment_horizon=horizon,
        investment_goal=InvestmentGoal.GROWTH,
        investment_experience=InvestmentExperience.INTERMEDIATE,
        liquidity_floor_pct={
            RiskProfile.CONSERVATIVE: 50,
            RiskProfile.MODERATE: 70,
            RiskProfile.AGGRESSIVE: 85,
        }[risk],
        max_atr_pctl_cap={
            RiskProfile.CONSERVATIVE: 60,
            RiskProfile.MODERATE: 75,
            RiskProfile.AGGRESSIVE: 90,
        }[risk],
        excluded_tickers=excluded_tickers or [],
        excluded_sectors=excluded_sectors or [],
        preferred_sectors=preferred_sectors or [],
        profile_version=1,
        is_active=True,
        confirmed_at=datetime(2026, 11, 14, tzinfo=UTC),
    )
    snapshot = SimpleNamespace(
        id=uuid4(),
        ticker="COMI.CA",
        date=date(2026, 11, 12),
        calculated_at=datetime(2026, 11, 12, 15, 30, tzinfo=UTC),
        config_version="technical-v1",
        input_hash="b" * 64,
        data_quality_status=status,
        rsi=55.0,
        sma_20=50.0,
        sma_50=48.0,
        atr=2.0,
        setup_score=70.0,
        regime="trending",
        risk_label="medium",
        input_data={},
        indicators={
            "atr_pct": 2.0,
            "atr_pct_percentile_1y": 60.0,
            "liquidity_rank_pct": liquidity_rank_pct,
            "volume_reliable": True,
            "breakdown": False,
            **(indicators or {}),
        },
        scores={
            "family_scores": {
                "trend": {"score": 70.0, "reliable": True},
                "momentum": {"score": 55.0, "reliable": True},
                "volume": {"score": 50.0, "reliable": True},
                "support_resistance": {"score": 45.0, "reliable": True},
                **(family_scores or {}),
            }
        },
        quality_flags=[],
    )
    return RecommendationInputs(
        user_id=user_id,
        ticker="COMI.CA",
        profile=profile,
        snapshot=snapshot,
        sector=sector,
        liquidity_rank_pct=liquidity_rank_pct,
    )


def test_all_moderate_medium_gates_at_minimum_produce_buy() -> None:
    outcome = evaluate_decision(_inputs())

    assert outcome.decision == RecommendationDecision.BUY
    assert outcome.reasons == ()
    assert outcome.filters_passed == ("data_quality", "user_restrictions", "liquidity")
    assert outcome.family_gates["trend"].passed is True


def test_missing_profile_or_snapshot_produces_no_recommendation() -> None:
    complete = _inputs()
    no_profile = complete.model_copy(update={"profile": None})
    no_snapshot = complete.model_copy(update={"snapshot": None})

    profile_outcome = evaluate_decision(no_profile)
    snapshot_outcome = evaluate_decision(no_snapshot)

    assert profile_outcome.decision == RecommendationDecision.NO_RECOMMENDATION
    assert profile_outcome.reasons == ("active_profile_missing",)
    assert snapshot_outcome.decision == RecommendationDecision.NO_RECOMMENDATION
    assert snapshot_outcome.reasons == ("valid_snapshot_missing",)


def test_newest_stale_snapshot_produces_no_recommendation_with_stale_reason() -> None:
    inputs = _inputs().model_copy(
        update={"snapshot": None, "snapshot_status": "stale"}
    )

    outcome = evaluate_decision(inputs)

    assert outcome.decision == RecommendationDecision.NO_RECOMMENDATION
    assert outcome.reasons == ("stale_snapshot",)


def test_horizon_adjustments_change_family_minimums() -> None:
    short = family_minimums(RiskProfile.MODERATE, InvestmentHorizon.SHORT)
    long = family_minimums(RiskProfile.MODERATE, InvestmentHorizon.LONG)

    assert (short.trend, short.momentum, short.volume, short.support_resistance) == (
        60,
        60,
        50,
        45,
    )
    assert (long.trend, long.momentum, long.volume, long.support_resistance) == (
        70,
        40,
        35,
        30,
    )


def test_family_gate_failure_returns_watch_with_blocker() -> None:
    outcome = evaluate_decision(
        _inputs(family_scores={"momentum": {"score": 49, "reliable": True}})
    )

    assert outcome.decision == RecommendationDecision.WATCH
    assert outcome.reasons == ("momentum",)


@pytest.mark.parametrize(
    ("indicators", "families"),
    [
        ({}, {"trend": {"score": 39, "reliable": True}}),
        ({"breakdown": True}, {}),
        (
            {},
            {
                "momentum": {"score": 29, "reliable": True},
                "volume": {"score": 39, "reliable": True},
            },
        ),
    ],
)
def test_bearish_technical_trigger_returns_avoid(
    indicators: dict[str, object],
    families: dict[str, dict[str, object]],
) -> None:
    outcome = evaluate_decision(_inputs(indicators=indicators, family_scores=families))

    assert outcome.decision == RecommendationDecision.AVOID
    assert "bearish_technical_trigger" in outcome.reasons


def test_unreliable_volume_does_not_block_buy() -> None:
    outcome = evaluate_decision(
        _inputs(family_scores={"volume": {"score": 10, "reliable": False}})
    )

    assert outcome.decision == RecommendationDecision.BUY
    assert outcome.family_gates["volume"].passed is None


def test_low_liquidity_rank_excludes_stock_and_missing_rank_fails_closed() -> None:
    low = evaluate_decision(_inputs(liquidity_rank_pct=69.99))
    missing = evaluate_decision(_inputs(liquidity_rank_pct=None))

    assert low.decision == RecommendationDecision.EXCLUDED
    assert low.reasons == ("liquidity_below_profile_minimum",)
    assert missing.decision == RecommendationDecision.NO_RECOMMENDATION
    assert missing.reasons == ("liquidity_rank_unavailable",)


def test_profile_ticker_and_sector_restrictions_exclude_stock() -> None:
    ticker = evaluate_decision(_inputs(excluded_tickers=["COMI"]))
    sector = evaluate_decision(_inputs(excluded_sectors=["financial services"]))
    preference = evaluate_decision(_inputs(preferred_sectors=["Industrials"]))

    assert ticker.reasons == ("ticker_excluded",)
    assert sector.reasons == ("sector_restricted",)
    assert preference.reasons == ("sector_restricted",)
    assert all(item.decision == RecommendationDecision.EXCLUDED for item in (ticker, sector, preference))


def test_missing_sector_fails_closed_when_profile_has_sector_constraints() -> None:
    outcome = evaluate_decision(
        _inputs(preferred_sectors=["Financial Services"], sector=None)
    )

    assert outcome.decision == RecommendationDecision.NO_RECOMMENDATION
    assert outcome.reasons == ("sector_unavailable",)


def test_extreme_volatility_forces_watch() -> None:
    outcome = evaluate_decision(
        _inputs(
            risk=RiskProfile.AGGRESSIVE,
            liquidity_rank_pct=85,
            indicators={"atr_pct_percentile_1y": 96},
        )
    )

    assert outcome.decision == RecommendationDecision.WATCH
    assert "extreme_volatility" in outcome.reasons


def test_missing_volatility_or_required_family_score_fails_closed() -> None:
    missing_volatility = evaluate_decision(
        _inputs(indicators={"atr_pct_percentile_1y": None})
    )
    missing_trend = evaluate_decision(
        _inputs(family_scores={"trend": {"score": None, "reliable": True}})
    )

    assert missing_volatility.decision == RecommendationDecision.NO_RECOMMENDATION
    assert missing_volatility.reasons == ("volatility_percentile_unavailable",)
    assert missing_trend.decision == RecommendationDecision.NO_RECOMMENDATION
    assert missing_trend.reasons == ("trend_score_unavailable",)
