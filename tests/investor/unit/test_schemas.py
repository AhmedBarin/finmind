"""Unit tests for Investor Agent schemas and gating logic."""

from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.investor.schemas import (
    InvestmentExperience,
    InvestmentGoal,
    InvestmentHorizon,
    InvestorProfileConfirmRequest,
    InvestorProfileDraft,
    InvestorProfilePayload,
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
    # Conservative: top 50% liquidity, max 60% ATR percentile
    assert compute_gating_parameters(RiskProfile.CONSERVATIVE) == (50.0, 60.0)

    # Moderate: top 70% liquidity, max 75% ATR percentile
    assert compute_gating_parameters(RiskProfile.MODERATE) == (70.0, 75.0)

    # Aggressive: top 85% liquidity, max 90% ATR percentile
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


def test_payload_from_confirmation_auto_derives_gating() -> None:
    user_id = uuid4()
    now = datetime.now(timezone.utc)
    confirm_request = InvestorProfileConfirmRequest(
        risk_profile=RiskProfile.CONSERVATIVE,
        investment_horizon=InvestmentHorizon.LONG,
        investment_goal=InvestmentGoal.CAPITAL_PRESERVATION,
        investment_experience=InvestmentExperience.BEGINNER,
        excluded_sectors=["Real Estate"],
        excluded_tickers=["COMI"],
        preferred_sectors=["Banking"],
    )

    payload = InvestorProfilePayload.from_confirmation(
        user_id=user_id,
        confirmation=confirm_request,
        confirmed_at=now,
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
    assert payload.confirmed_at == now


def test_invalid_enum_raises_validation_error() -> None:
    with pytest.raises(ValidationError):
        InvestorProfileConfirmRequest(
            risk_profile="yolo",  # Invalid
            investment_horizon=InvestmentHorizon.SHORT,
            investment_goal=InvestmentGoal.GROWTH,
            investment_experience=InvestmentExperience.INTERMEDIATE,
        )

