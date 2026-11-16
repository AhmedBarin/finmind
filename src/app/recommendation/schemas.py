"""Versioned contracts for Recommendation Engine inputs and output."""

from __future__ import annotations

from datetime import date
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from app.investor.schemas import InvestorProfilePayload
from app.technical_analysis.schemas import TechnicalSnapshotRead


class RecommendationDecision(StrEnum):
    BUY = "BUY"
    WATCH = "WATCH"
    AVOID = "AVOID"
    EXCLUDED = "EXCLUDED"
    NO_RECOMMENDATION = "NO_RECOMMENDATION"


class ConfidenceLevel(StrEnum):
    HIGH = "High"
    MEDIUM = "Medium"
    LOW = "Low"


class RecommendationEvaluateRequest(BaseModel):
    """Request to evaluate one ticker for the authenticated user."""

    ticker: str = Field(min_length=1, max_length=32)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        ticker = value.strip().upper()
        if not ticker:
            raise ValueError("ticker must not be empty")
        return ticker


class RecommendationInputs(BaseModel):
    """Read-only profile and latest valid snapshot used by a decision."""

    model_config = ConfigDict(arbitrary_types_allowed=False)

    user_id: UUID
    ticker: str = Field(min_length=1, max_length=32)
    profile: InvestorProfilePayload | None
    snapshot: TechnicalSnapshotRead | None

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str) -> str:
        ticker = value.strip().upper()
        if not ticker:
            raise ValueError("ticker must not be empty")
        return ticker

    @model_validator(mode="after")
    def validate_sources(self) -> "RecommendationInputs":
        if self.profile is not None:
            if self.profile.user_id != self.user_id:
                raise ValueError("profile belongs to a different user")
            if not self.profile.is_active:
                raise ValueError("only an active confirmed profile may be used")
        if self.snapshot is not None:
            if self.snapshot.ticker.strip().upper() != self.ticker:
                raise ValueError("snapshot ticker does not match requested ticker")
            if self.snapshot.data_quality_status != "valid":
                raise ValueError("recommendation input snapshot must be valid")
        return self


class FamilyResult(BaseModel):
    score: float | None = Field(default=None, ge=0, le=100)
    state: str | None = None
    min_required: float | None = Field(default=None, ge=0, le=100)
    passed: bool | None = None
    reliable: bool | None = None


class VolatilityResult(BaseModel):
    atr_pct: float | None = Field(default=None, ge=0)
    percentile: float | None = Field(default=None, ge=0, le=100)
    label: str | None = None
    cap: float | None = Field(default=None, ge=0, le=100)
    passed: bool | None = None


class RecommendationFamilies(BaseModel):
    trend: FamilyResult = Field(default_factory=FamilyResult)
    momentum: FamilyResult = Field(default_factory=FamilyResult)
    volume: FamilyResult = Field(default_factory=FamilyResult)
    support_resistance: FamilyResult = Field(default_factory=FamilyResult)
    volatility: VolatilityResult = Field(default_factory=VolatilityResult)


class UserFit(BaseModel):
    risk_profile: str
    horizon: str
    goal: str


class RecommendationDataQuality(BaseModel):
    price_status: str
    last_price_date: date | None


class RecommendationResult(BaseModel):
    """Structured recommendation payload for downstream explanation and APIs."""

    ticker: str
    trading_date: date | None
    snapshot_id: UUID | None = None
    config_version: str
    decision: RecommendationDecision
    watch_reasons: list[str] = Field(default_factory=list)
    confidence: ConfidenceLevel
    setup_score: float | None = Field(default=None, ge=0, le=100)
    regime: str | None = None
    families: RecommendationFamilies = Field(default_factory=RecommendationFamilies)
    indicators: dict[str, float | None] = Field(default_factory=dict)
    user_fit: UserFit | None = None
    rules: dict[str, list[str]] = Field(default_factory=dict)
    what_would_change_it: list[str] = Field(default_factory=list)
    data_quality: RecommendationDataQuality
