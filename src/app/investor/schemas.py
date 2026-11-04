"""Investor Agent schemas and deterministic data contracts."""

from datetime import datetime
from enum import StrEnum
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class RiskProfile(StrEnum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class InvestmentHorizon(StrEnum):
    SHORT = "short"
    MEDIUM = "medium"
    LONG = "long"


class InvestmentGoal(StrEnum):
    CAPITAL_PRESERVATION = "capital_preservation"
    GROWTH = "growth"
    INCOME = "income"
    SPECULATION = "speculation"


class InvestmentExperience(StrEnum):
    BEGINNER = "beginner"
    INTERMEDIATE = "intermediate"
    ADVANCED = "advanced"


# Deterministic mapping of risk profile to technical gating parameters
# (liquidity_floor_pct, max_atr_pctl_cap)
# Reference: FinMind Unified Spec, Section 6.2
GATING_MATRIX: dict[RiskProfile, tuple[float, float]] = {
    RiskProfile.CONSERVATIVE: (50.0, 60.0),
    RiskProfile.MODERATE: (70.0, 75.0),
    RiskProfile.AGGRESSIVE: (85.0, 90.0),
}


def compute_gating_parameters(risk_profile: RiskProfile) -> tuple[float, float]:
    """Deterministically derive liquidity floor and volatility cap from risk profile.

    Returns:
        tuple[float, float]: (liquidity_floor_pct, max_atr_pctl_cap)
    """
    if risk_profile not in GATING_MATRIX:
        raise ValueError(f"Unknown risk profile: {risk_profile}")
    return GATING_MATRIX[risk_profile]


class InvestorProfileBase(BaseModel):
    """Base fields shared across profile representations."""

    risk_profile: RiskProfile
    investment_horizon: InvestmentHorizon
    investment_goal: InvestmentGoal
    investment_experience: InvestmentExperience
    excluded_sectors: list[str] = Field(default_factory=list)
    excluded_tickers: list[str] = Field(default_factory=list)
    preferred_sectors: list[str] = Field(default_factory=list)


class InvestorProfileDraft(BaseModel):
    """In-progress draft accumulated during conversational interview turns.

    All profiling dimensions are optional until the interview is complete.
    """

    risk_tolerance_raw: str | None = None
    risk_capacity_raw: str | None = None
    derived_risk_profile: RiskProfile | None = None
    investment_horizon: InvestmentHorizon | None = None
    investment_goal: InvestmentGoal | None = None
    investment_experience: InvestmentExperience | None = None
    excluded_sectors: list[str] = Field(default_factory=list)
    excluded_tickers: list[str] = Field(default_factory=list)
    preferred_sectors: list[str] = Field(default_factory=list)

    def is_complete(self) -> bool:
        """Check if all required dimensions have been extracted."""
        return all(
            [
                self.derived_risk_profile is not None,
                self.investment_horizon is not None,
                self.investment_goal is not None,
                self.investment_experience is not None,
            ]
        )


class InvestorProfileConfirmRequest(InvestorProfileBase):
    """User confirmation request submitted via HITL summary card.

    Allows user to review and optionally edit parameters before confirming.
    """

    pass


class InvestorProfilePayload(InvestorProfileBase):
    """Canonical confirmed profile contract consumed by the Recommendation Engine.

    Reference: FinMind Unified Spec, Section 4.3
    """

    user_id: UUID
    liquidity_floor_pct: Annotated[float, Field(ge=0.0, le=100.0)]
    max_atr_pctl_cap: Annotated[float, Field(ge=0.0, le=100.0)]
    profile_version: int = Field(default=1, ge=1)
    is_active: bool = True
    confirmed_at: datetime

    model_config = ConfigDict(from_attributes=True)

    @classmethod
    def from_confirmation(
        cls,
        user_id: UUID,
        confirmation: InvestorProfileConfirmRequest,
        confirmed_at: datetime | None = None,
        profile_version: int = 1,
    ) -> "InvestorProfilePayload":
        """Factory method deriving technical gating parameters deterministically."""
        liquidity_floor, max_atr_cap = compute_gating_parameters(
            confirmation.risk_profile
        )
        return cls(
            user_id=user_id,
            risk_profile=confirmation.risk_profile,
            investment_horizon=confirmation.investment_horizon,
            investment_goal=confirmation.investment_goal,
            investment_experience=confirmation.investment_experience,
            excluded_sectors=confirmation.excluded_sectors,
            excluded_tickers=confirmation.excluded_tickers,
            preferred_sectors=confirmation.preferred_sectors,
            liquidity_floor_pct=liquidity_floor,
            max_atr_pctl_cap=max_atr_cap,
            profile_version=profile_version,
            is_active=True,
            confirmed_at=confirmed_at or datetime.now(),
        )

