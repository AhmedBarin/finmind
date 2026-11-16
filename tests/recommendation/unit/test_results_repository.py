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
from app.recommendation.config import RECOMMENDATION_CONFIG_VERSION
from app.recommendation.decision import DecisionEvaluation, FamilyGate, evaluate_decision
from app.recommendation.models import RecommendationLog
from app.recommendation.repository import (
    get_recommendation_history,
    save_recommendation_log,
)
from app.recommendation.results import (
    build_recommendation_result,
    calculate_confidence,
)
from app.recommendation.schemas import (
    ConfidenceLevel,
    RecommendationDecision,
    RecommendationInputs,
)


def _inputs(
    *,
    family_scores: dict[str, dict[str, object]] | None = None,
    indicators: dict[str, object] | None = None,
    quality_flags: list[str] | None = None,
) -> RecommendationInputs:
    user_id = uuid4()
    profile = InvestorProfilePayload(
        user_id=user_id,
        risk_profile=RiskProfile.MODERATE,
        investment_horizon=InvestmentHorizon.MEDIUM,
        investment_goal=InvestmentGoal.GROWTH,
        investment_experience=InvestmentExperience.INTERMEDIATE,
        liquidity_floor_pct=70,
        max_atr_pctl_cap=75,
        profile_version=3,
        is_active=True,
        confirmed_at=datetime(2026, 11, 14, tzinfo=UTC),
    )
    snapshot = SimpleNamespace(
        id=uuid4(),
        ticker="COMI.CA",
        date=date(2026, 11, 12),
        calculated_at=datetime(2026, 11, 12, 15, 30, tzinfo=UTC),
        config_version="technical-v1",
        input_hash="c" * 64,
        data_quality_status="valid",
        rsi=55.0,
        sma_20=50.0,
        sma_50=48.0,
        atr=2.0,
        setup_score=70.0,
        regime="trending",
        risk_label="medium",
        input_data={},
        indicators={
            "close": 51.0,
            "sma20": 50.0,
            "sma50": 48.0,
            "sma200": 44.0,
            "rsi14": 55.0,
            "macd": 1.1,
            "macd_signal": 0.9,
            "adx14": 26.0,
            "volume_ratio": 1.3,
            "support": 47.0,
            "resistance": 53.0,
            "atr_pct": 2.0,
            "atr_pct_percentile_1y": 60.0,
            "breakdown": False,
            **(indicators or {}),
        },
        scores={
            "family_scores": {
                "trend": {"score": 75.0, "state": "bullish", "reliable": True},
                "momentum": {"score": 60.0, "state": "neutral", "reliable": True},
                "volume": {"score": 55.0, "state": "neutral", "reliable": True},
                "support_resistance": {
                    "score": 50.0,
                    "state": "neutral",
                    "reliable": True,
                },
                **(family_scores or {}),
            }
        },
        quality_flags=quality_flags or [],
    )
    return RecommendationInputs(
        user_id=user_id,
        ticker="COMI.CA",
        profile=profile,
        snapshot=snapshot,
        sector="Financial Services",
        liquidity_rank_pct=70,
    )


def _evaluation(
    *,
    decision: RecommendationDecision = RecommendationDecision.BUY,
    reasons: tuple[str, ...] = (),
    trend: FamilyGate = FamilyGate(75, 65, True, True),
    momentum: FamilyGate = FamilyGate(60, 50, True, True),
    volume: FamilyGate = FamilyGate(55, 45, True, True),
    support_resistance: FamilyGate = FamilyGate(50, 40, True, True),
    volatility: FamilyGate = FamilyGate(60, 75, True, True),
) -> DecisionEvaluation:
    return DecisionEvaluation(
        decision=decision,
        reasons=reasons,
        filters_passed=("data_quality", "user_restrictions", "liquidity"),
        family_gates={
            "trend": trend,
            "momentum": momentum,
            "volume": volume,
            "support_resistance": support_resistance,
            "volatility": volatility,
        },
        liquidity_rank_minimum=70,
        atr_percentile_cap=75,
    )


def test_confidence_is_high_when_multiple_independent_checks_are_strong() -> None:
    inputs = _inputs()
    outcome = evaluate_decision(inputs)

    assert calculate_confidence(inputs, outcome) == ConfidenceLevel.HIGH


def test_confidence_rewards_evidence_and_penalizes_borderline_families() -> None:
    inputs = _inputs(
        family_scores={"volume": {"score": 50, "state": "neutral", "reliable": True}},
        indicators={"atr_pct_percentile_1y": 65},
    )
    outcome = evaluate_decision(inputs)

    assert calculate_confidence(inputs, outcome) == ConfidenceLevel.MEDIUM


def test_confidence_is_low_when_required_inputs_are_missing() -> None:
    inputs = _inputs().model_copy(update={"snapshot": None})
    outcome = DecisionEvaluation(
        decision=RecommendationDecision.NO_RECOMMENDATION,
        reasons=("valid_snapshot_missing",),
        filters_passed=(),
        family_gates={},
        liquidity_rank_minimum=None,
        atr_percentile_cap=None,
    )

    assert calculate_confidence(inputs, outcome) == ConfidenceLevel.LOW


def test_excluded_results_have_low_recommendation_confidence() -> None:
    inputs = _inputs()
    outcome = _evaluation(
        decision=RecommendationDecision.EXCLUDED,
        reasons=("sector_restricted",),
    )

    assert calculate_confidence(inputs, outcome) == ConfidenceLevel.LOW


def test_result_builder_includes_audit_context_user_fit_and_reasons() -> None:
    inputs = _inputs()
    evaluation = _evaluation(
        decision=RecommendationDecision.WATCH,
        reasons=("momentum", "volatility"),
        momentum=FamilyGate(49, 50, False, True),
        volatility=FamilyGate(80, 75, False, True),
    )

    result = build_recommendation_result(inputs, evaluation)
    payload = result.model_dump(mode="json")

    assert result.ticker == "COMI.CA"
    assert result.trading_date == inputs.snapshot.date
    assert result.snapshot_id == inputs.snapshot.id
    assert result.config_version == RECOMMENDATION_CONFIG_VERSION
    assert result.decision == RecommendationDecision.WATCH
    assert result.reasons == ["momentum", "volatility"]
    assert result.watch_reasons == ["momentum", "volatility"]
    assert result.user_fit is not None
    assert result.user_fit.risk_profile == "moderate"
    assert result.families.momentum.passed is False
    assert result.families.volatility.percentile == 80
    assert result.what_would_change_it
    assert "news" not in payload


@pytest.mark.asyncio
async def test_save_recommendation_log_persists_required_audit_fields() -> None:
    inputs = _inputs()
    evaluation = _evaluation(
        decision=RecommendationDecision.WATCH,
        reasons=("momentum",),
    )
    result = build_recommendation_result(inputs, evaluation)

    class FakeSession:
        row: RecommendationLog | None = None

        def add(self, row: RecommendationLog) -> None:
            self.row = row

        async def flush(self) -> None:
            return None

    session = FakeSession()
    saved = await save_recommendation_log(
        session, user_id=inputs.user_id, result=result
    )

    assert saved is session.row
    assert saved.user_id == inputs.user_id
    assert saved.ticker == inputs.ticker
    assert saved.trading_date == inputs.snapshot.date
    assert saved.snapshot_id == inputs.snapshot.id
    assert saved.config_version == RECOMMENDATION_CONFIG_VERSION
    assert saved.decision == "WATCH"
    assert saved.blockers == ["momentum"]
    assert saved.confidence == result.confidence.value


@pytest.mark.asyncio
async def test_history_is_user_scoped_and_normalizes_ticker() -> None:
    user_id = uuid4()
    statement_seen = None

    class FakeResult:
        def all(self) -> list[object]:
            return []

    class FakeSession:
        async def scalars(self, statement):
            nonlocal statement_seen
            statement_seen = statement
            return FakeResult()

    rows = await get_recommendation_history(
        FakeSession(),
        user_id=user_id,
        ticker=" comi.ca ",
        limit=25,
    )

    assert rows == []
    assert statement_seen is not None
    assert "recommendation_logs.user_id" in str(statement_seen)
    assert "recommendation_logs.ticker" in str(statement_seen)


@pytest.mark.asyncio
async def test_history_rejects_out_of_range_limit() -> None:
    with pytest.raises(ValueError, match="between 1 and 500"):
        await get_recommendation_history(None, user_id=uuid4(), limit=0)
