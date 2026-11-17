"""Unit tests for deterministic risk matrix and coherence validation."""

import pytest

from app.investor.assessment import (
    assess_risk_profile,
    compute_missing_dimensions,
    is_off_topic_stock_query,
    validate_coherence,
)
from app.investor.schemas import (
    InvestmentExperience,
    InvestmentGoal,
    InvestmentHorizon,
    RiskCapacity,
    RiskProfile,
    RiskWillingness,
)


@pytest.mark.parametrize(
    ("capacity", "willingness", "expected", "capped"),
    [
        (RiskCapacity.LOW, RiskWillingness.CONSERVATIVE, RiskProfile.CONSERVATIVE, False),
        (RiskCapacity.LOW, RiskWillingness.MODERATE, RiskProfile.CONSERVATIVE, False),
        (RiskCapacity.LOW, RiskWillingness.AGGRESSIVE, RiskProfile.MODERATE, True),
        (RiskCapacity.MEDIUM, RiskWillingness.CONSERVATIVE, RiskProfile.CONSERVATIVE, False),
        (RiskCapacity.MEDIUM, RiskWillingness.MODERATE, RiskProfile.MODERATE, False),
        (RiskCapacity.MEDIUM, RiskWillingness.AGGRESSIVE, RiskProfile.AGGRESSIVE, False),
        (RiskCapacity.HIGH, RiskWillingness.CONSERVATIVE, RiskProfile.MODERATE, False),
        (RiskCapacity.HIGH, RiskWillingness.MODERATE, RiskProfile.AGGRESSIVE, False),
        (RiskCapacity.HIGH, RiskWillingness.AGGRESSIVE, RiskProfile.AGGRESSIVE, False),
    ],
)
def test_risk_matrix_all_cells(
    capacity: RiskCapacity,
    willingness: RiskWillingness,
    expected: RiskProfile,
    capped: bool,
) -> None:
    result = assess_risk_profile(capacity, willingness)
    assert result.risk_profile is expected
    assert result.safety_cap_applied is capped
    if capped:
        assert result.cap_reason_ar is not None
    else:
        assert result.cap_reason_ar is None


def test_validate_coherence_detects_zero_risk_high_return_contradiction() -> None:
    result = validate_coherence(
        investment_goal=InvestmentGoal.GROWTH,
        investment_horizon=InvestmentHorizon.SHORT,
        risk_capacity=RiskCapacity.MEDIUM,
        risk_willingness=RiskWillingness.AGGRESSIVE,
        derived_risk_profile=None,
        investment_experience=InvestmentExperience.BEGINNER,
        zero_loss_high_return_claim=True,
    )
    assert result.is_coherent is False
    assert "zero_risk_high_return_contradiction" in result.conflicts
    assert result.clarification_prompt_ar is not None
    assert result.is_complete is False


def test_validate_coherence_detects_goal_willingness_and_speculation_conflicts() -> None:
    result = validate_coherence(
        investment_goal=InvestmentGoal.CAPITAL_PRESERVATION,
        investment_horizon=InvestmentHorizon.LONG,
        risk_capacity=RiskCapacity.HIGH,
        risk_willingness=RiskWillingness.AGGRESSIVE,
        derived_risk_profile=None,
        investment_experience=InvestmentExperience.INTERMEDIATE,
    )
    assert "goal_vs_willingness_contradiction" in result.conflicts

    spec_low = validate_coherence(
        investment_goal=InvestmentGoal.SPECULATION,
        investment_horizon=InvestmentHorizon.SHORT,
        risk_capacity=RiskCapacity.LOW,
        risk_willingness=RiskWillingness.AGGRESSIVE,
        derived_risk_profile=None,
        investment_experience=InvestmentExperience.BEGINNER,
    )
    assert spec_low.derived_risk_profile is RiskProfile.MODERATE
    assert spec_low.safety_cap_applied is True
    assert "speculation_with_low_capacity" in spec_low.conflicts


def test_compute_missing_dimensions_follows_interview_order() -> None:
    assert compute_missing_dimensions(
        investment_goal=None,
        investment_horizon=None,
        derived_risk_profile=None,
        investment_experience=None,
    ) == ("investment_goal", "investment_horizon", "risk_profile", "investment_experience")

    assert compute_missing_dimensions(
        investment_goal=InvestmentGoal.INCOME,
        investment_horizon=InvestmentHorizon.LONG,
        derived_risk_profile=None,
        investment_experience=InvestmentExperience.ADVANCED,
    ) == ("risk_profile",)


def test_off_topic_stock_query_detection() -> None:
    assert is_off_topic_stock_query("هل أشتري سهم التجاري الدولي دلوقتي؟") is True
    assert is_off_topic_stock_query("Should I buy COMI right now?") is True
    assert is_off_topic_stock_query("أفضل الاستثمار على مدى عام لحماية المدخرات") is False


@pytest.mark.parametrize(
    "message",
    [
        "لقد اشتريت شقة جديدة وأحتاج للسيولة قريباً",
        "بعت عربيتي واشتريت أرض",
        "I bought shares before; should I worry about recommendations later?",
    ],
)
def test_off_topic_ignores_past_tense_and_partial_words(message: str) -> None:
    assert is_off_topic_stock_query(message) is False


@pytest.mark.parametrize(
    "message",
    [
        "واشتري إيه دلوقتي؟",
        "عايز التوصية بتاعتك",
        "ممكن توصيات؟",
        "هل ابيع السهم؟",
    ],
)
def test_off_topic_detects_triggers_with_arabic_proclitics(message: str) -> None:
    assert is_off_topic_stock_query(message) is True

