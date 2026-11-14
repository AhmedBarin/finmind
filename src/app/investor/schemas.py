"""Investor Agent schemas and deterministic data contracts."""

from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator


class RiskProfile(StrEnum):
    CONSERVATIVE = "conservative"
    MODERATE = "moderate"
    AGGRESSIVE = "aggressive"


class RiskCapacity(StrEnum):
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"


class RiskWillingness(StrEnum):
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


class ProfileAuditChangeType(StrEnum):
    INITIAL_CREATION = "initial_creation"
    USER_EDIT = "user_edit"
    RE_PROFILING = "re_profiling"
    PREFERENCE_UPDATE = "preference_update"


class AuditChangedBy(StrEnum):
    USER = "user"
    ADMIN = "admin"
    SCHEDULED_REVIEW = "scheduled_review"


# Deterministic mapping of risk profile to technical gating parameters
# (liquidity_floor_pct, max_atr_pctl_cap)
# Reference: FinMind Unified Spec, Section 6.2 & Module 2 Section 4.5
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


def _normalize_string_list(values: list[str], *, uppercase: bool = False) -> list[str]:
    """Strip blanks and deduplicate while preserving order."""
    seen: set[str] = set()
    normalized: list[str] = []
    for raw in values:
        cleaned = raw.strip()
        if uppercase:
            cleaned = cleaned.upper()
        if cleaned and cleaned not in seen:
            seen.add(cleaned)
            normalized.append(cleaned)
    return normalized


class InvestorProfileBase(BaseModel):
    """Base fields shared across profile representations."""

    risk_profile: RiskProfile
    investment_horizon: InvestmentHorizon
    investment_goal: InvestmentGoal
    investment_experience: InvestmentExperience
    excluded_sectors: list[str] = Field(default_factory=list)
    excluded_tickers: list[str] = Field(default_factory=list)
    preferred_sectors: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def _clean_lists(self) -> "InvestorProfileBase":
        self.excluded_sectors = _normalize_string_list(self.excluded_sectors)
        self.excluded_tickers = _normalize_string_list(
            self.excluded_tickers, uppercase=True
        )
        self.preferred_sectors = _normalize_string_list(self.preferred_sectors)
        return self


class InvestorProfileDraft(BaseModel):
    """In-progress draft accumulated during conversational interview turns.

    All profiling dimensions are optional until the interview is complete.
    """

    risk_tolerance_raw: str | None = None
    risk_capacity_raw: str | None = None
    risk_capacity: RiskCapacity | None = None
    risk_willingness: RiskWillingness | None = None
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

    reason: str | None = Field(default=None, max_length=500)


class ConstraintsUpdateRequest(BaseModel):
    """Partial update request for excluded sectors, tickers, or preferred sectors."""

    excluded_sectors: list[str] | None = None
    excluded_tickers: list[str] | None = None
    preferred_sectors: list[str] | None = None
    reason: str | None = Field(default=None, max_length=500)

    @model_validator(mode="after")
    def _validate_non_empty_update(self) -> "ConstraintsUpdateRequest":
        if (
            self.excluded_sectors is None
            and self.excluded_tickers is None
            and self.preferred_sectors is None
        ):
            raise ValueError("At least one constraint list must be provided")
        if self.excluded_sectors is not None:
            self.excluded_sectors = _normalize_string_list(self.excluded_sectors)
        if self.excluded_tickers is not None:
            self.excluded_tickers = _normalize_string_list(
                self.excluded_tickers, uppercase=True
            )
        if self.preferred_sectors is not None:
            self.preferred_sectors = _normalize_string_list(self.preferred_sectors)
        return self


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
            confirmed_at=confirmed_at or datetime.now(UTC),
        )


class ExtractedProfileParameters(InvestorProfileBase):
    """Profile parameters presented inside the HITL summary card before DB save."""

    liquidity_floor_pct: Annotated[float, Field(ge=0.0, le=100.0)]
    max_atr_pctl_cap: Annotated[float, Field(ge=0.0, le=100.0)]


class ProfileSummaryCardAr(BaseModel):
    """Arabic display payload for Human-in-the-Loop confirmation (Spec Section 9)."""

    title: str
    risk_level_display: str
    horizon_display: str
    goal_display: str
    experience_display: str
    constraints_summary: list[str] = Field(default_factory=list)
    recommendation_engine_impact: str


class HITLSummaryCard(BaseModel):
    """Complete HITL review payload emitted when interview dimensions are complete."""

    profile_summary_ar: ProfileSummaryCardAr
    extracted_parameters: ExtractedProfileParameters
    requires_user_confirmation: bool = True


class InterviewMessageRequest(BaseModel):
    """Incoming chat message payload for POST /investor/interview/message."""

    session_id: UUID
    message: str = Field(min_length=1, max_length=2000)


class InterviewStateView(BaseModel):
    """Public snapshot of interview progress returned alongside agent turns."""

    current_step: str | None = None
    is_complete: bool = False
    is_confirmed: bool = False
    missing_dimensions: list[str] = Field(default_factory=list)
    detected_conflicts: list[str] = Field(default_factory=list)
    safety_cap_applied: bool = False


class InterviewMessageResponse(BaseModel):
    """Outgoing interview response payload (Spec Section 10.1)."""

    session_id: UUID
    agent_message_ar: str
    state: InterviewStateView
    summary_card: HITLSummaryCard | None = None


class ProfileAuditLogRead(BaseModel):
    """Serialized view of an immutable profile audit log entry."""

    id: UUID
    profile_id: UUID
    user_id: UUID
    change_type: ProfileAuditChangeType
    previous_state: dict[str, Any] | None = None
    new_state: dict[str, Any]
    reason: str | None = None
    changed_by: AuditChangedBy
    created_at: datetime

    model_config = ConfigDict(from_attributes=True)


class LearnedPreferenceCreate(BaseModel):
    """Validated input for recording an inferred preference (Spec Section 4.2)."""

    preference_key: str = Field(min_length=1, max_length=100)
    preference_value: dict[str, Any]
    confidence_score: Annotated[float, Field(ge=0.0, le=1.0)]
    source_event: str = Field(min_length=1, max_length=100)
    user_validated: bool = False


class LearnedPreferenceRead(LearnedPreferenceCreate):
    """Serialized view of a persisted learned preference."""

    id: UUID
    user_id: UUID
    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(from_attributes=True)


RISK_PROFILE_RANK: dict[RiskProfile, int] = {
    RiskProfile.CONSERVATIVE: 0,
    RiskProfile.MODERATE: 1,
    RiskProfile.AGGRESSIVE: 2,
}


class ProfileOverrides(BaseModel):
    """User edits applied to the HITL summary card before confirmation."""

    risk_profile: RiskProfile | None = None
    investment_horizon: InvestmentHorizon | None = None
    investment_goal: InvestmentGoal | None = None
    investment_experience: InvestmentExperience | None = None
    excluded_sectors: list[str] | None = None
    excluded_tickers: list[str] | None = None
    preferred_sectors: list[str] | None = None

    model_config = ConfigDict(extra="forbid")


class SessionConfirmRequest(BaseModel):
    """HITL confirmation for POST /investor/profile/confirm (Spec Section 10.2).

    ``session_id`` identifies the interview whose summary card is being
    confirmed (the spec's ``draft_profile_id``). Raising the risk level above
    the derived/capped value requires ``accept_risk_disclaimer``.
    """

    session_id: UUID
    user_overrides: ProfileOverrides | None = None
    accept_risk_disclaimer: bool = False
    reason: str | None = Field(default=None, max_length=500)


class ConfirmedProfileResponse(BaseModel):
    """Activated profile returned after HITL confirmation."""

    profile_id: UUID
    profile: InvestorProfilePayload
    agent_message_ar: str


class RecommendationFeedbackRequest(BaseModel):
    """Episodic feedback on a recommendation or alert (Spec Section 7.1, tier 3)."""

    feedback: str = Field(pattern="^(too_volatile|good_timing|not_interested)$")
    ticker: str | None = Field(default=None, max_length=20)
