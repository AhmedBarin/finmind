"""Unit tests for Investor Agent schemas and gating logic."""

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.investor.schemas import (
    ConstraintsUpdateRequest,
    InterviewMessageRequest,
    InvestmentExperience,
    InvestmentGoal,
    InvestmentHorizon,
    InvestorProfileConfirmRequest,
    InvestorProfileDraft,
    InvestorProfilePayload,
    LearnedPreferenceCreate,
    RiskProfile,
    compute_gating_parameters,
)


def test_risk_profile_values() -> None:
    assert RiskProfile.CONSERVATIVE == "conservative"
    assert RiskProfile.MODERATE == "moderate"
    assert RiskProfile.AGGRESSIVE == "aggressive"


def test_investment_horizon_values() -> None:
    assert InvestmentHorizon.SHORT == "short"
    assert InvestmentHorizon.MEDIUM == "medium"
    assert InvestmentHorizon.LONG == "long"


def test_compute_gating_parameters_deterministic() -> None:
    assert compute_gating_parameters(RiskProfile.CONSERVATIVE) == (50.0, 60.0)
    assert compute_gating_parameters(RiskProfile.MODERATE) == (70.0, 75.0)
    assert compute_gating_parameters(RiskProfile.AGGRESSIVE) == (85.0, 90.0)


def test_draft_completeness_check() -> None:
    draft = InvestorProfileDraft()
    assert draft.is_complete() is False

    draft.derived_risk_profile = RiskProfile.MODERATE
    draft.investment_horizon = InvestmentHorizon.MEDIUM
    assert draft.is_complete() is False

    draft.investment_goal = InvestmentGoal.GROWTH
    assert draft.is_complete() is False

    draft.investment_experience = InvestmentExperience.INTERMEDIATE
    assert draft.is_complete() is True


def test_payload_from_confirmation_auto_derives_gating_and_utc_timestamp() -> None:
    user_id = uuid4()
    confirm_request = InvestorProfileConfirmRequest(
        risk_profile=RiskProfile.CONSERVATIVE,
        investment_horizon=InvestmentHorizon.LONG,
        investment_goal=InvestmentGoal.CAPITAL_PRESERVATION,
        investment_experience=InvestmentExperience.BEGINNER,
        excluded_sectors=["Real Estate", " Real Estate "],
        excluded_tickers=["comi", "COMI"],
        preferred_sectors=["Banking"],
    )

    payload = InvestorProfilePayload.from_confirmation(
        user_id=user_id,
        confirmation=confirm_request,
    )

    assert payload.user_id == user_id
    assert payload.risk_profile == RiskProfile.CONSERVATIVE
    assert payload.liquidity_floor_pct == 50.0
    assert payload.max_atr_pctl_cap == 60.0
    assert payload.is_active is True
    assert payload.profile_version == 1
    assert payload.excluded_sectors == ["Real Estate"]
    assert payload.excluded_tickers == ["COMI"]
    assert payload.preferred_sectors == ["Banking"]
    assert payload.confirmed_at.tzinfo is UTC


def test_invalid_enum_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        InvestorProfileConfirmRequest(
            risk_profile="yolo",  # type: ignore[arg-type]
            investment_horizon=InvestmentHorizon.SHORT,
            investment_goal=InvestmentGoal.GROWTH,
            investment_experience=InvestmentExperience.INTERMEDIATE,
        )


def test_constraints_update_requires_at_least_one_field_and_normalizes_tickers() -> None:
    with pytest.raises(ValidationError):
        ConstraintsUpdateRequest()

    req = ConstraintsUpdateRequest(excluded_tickers=[" comi ", "hrho", "COMI"])
    assert req.excluded_tickers == ["COMI", "HRHO"]


def test_learned_preference_confidence_bounded() -> None:
    valid = LearnedPreferenceCreate(
        preference_key="dividend_focused",
        preference_value={"preferred": True},
        confidence_score=0.85,
        source_event="conversation",
    )
    assert valid.confidence_score == 0.85

    with pytest.raises(ValidationError):
        LearnedPreferenceCreate(
            preference_key="bad",
            preference_value={},
            confidence_score=1.2,
            source_event="conversation",
        )


def test_interview_message_request_rejects_empty_text() -> None:
    with pytest.raises(ValidationError):
        InterviewMessageRequest(session_id=uuid4(), message="")
