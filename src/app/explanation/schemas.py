"""Pydantic contracts shared by all Explanation Agent modes.

These contracts intentionally contain prepared upstream data. The Explanation
Agent may interpret it, but it does not own recommendation or technical
calculation decisions.
"""

from __future__ import annotations

from datetime import date, datetime
from enum import StrEnum
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.explanation.constants import EXPLANATION_SCHEMA_VERSION
from app.monitoring.schemas.alerts import AlertResponse
from app.recommendation.schemas import RecommendationDecision, RecommendationResult
from app.technical_analysis.schemas import TechnicalSnapshotRead


class ExplanationMode(StrEnum):
    RECOMMENDATION = "recommendation"
    ALERT = "alert"
    FOLLOW_UP = "follow_up"
    STOCK_QA = "stock_qa"


class DataAvailability(StrEnum):
    AVAILABLE = "available"
    NOT_FOUND = "not_found"
    STALE = "stale"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


class ExplanationLanguage(StrEnum):
    ARABIC = "ar"
    ENGLISH = "en"


class EvidenceItem(BaseModel):
    """A source-backed item supplied to the model as untrusted evidence."""

    model_config = ConfigDict(extra="forbid")

    evidence_id: str = Field(min_length=1, max_length=128)
    article_id: UUID | None = None
    source_id: UUID | None = None
    source_name: str | None = Field(default=None, max_length=200)
    title: str = Field(min_length=1, max_length=1000)
    source_url: str | None = Field(default=None, max_length=2048)
    published_at: datetime | None = None
    excerpt: str | None = None
    quote: str | None = None
    ticker: str | None = Field(default=None, max_length=32)
    availability: DataAvailability = DataAvailability.AVAILABLE

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None and value.strip() else None


class EvidenceQuery(BaseModel):
    """Deterministic query envelope for authorized evidence retrieval."""

    ticker: str | None = Field(default=None, min_length=1, max_length=32)
    as_of: date | None = None
    query_text: str = Field(default="", max_length=1000)
    reasons: list[str] = Field(default_factory=list, max_length=20)
    alert_type: str | None = Field(default=None, max_length=100)
    limit: int = Field(default=10, ge=1, le=50)

    @field_validator("ticker")
    @classmethod
    def normalize_ticker(cls, value: str | None) -> str | None:
        return value.strip().upper() if value is not None and value.strip() else None


class EvidenceResult(BaseModel):
    status: DataAvailability
    items: list[EvidenceItem] = Field(default_factory=list, max_length=50)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    freshness_seconds: int | None = Field(default=None, ge=0)


class RecommendationExplanationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recommendation: RecommendationResult
    news_evidence: list[EvidenceItem] = Field(default_factory=list, max_length=50)
    language: ExplanationLanguage = ExplanationLanguage.ARABIC
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)


class AlertExplanationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    alert: AlertResponse
    old_snapshot: TechnicalSnapshotRead | None = None
    new_snapshot: TechnicalSnapshotRead | None = None
    news_evidence: list[EvidenceItem] = Field(default_factory=list, max_length=50)
    language: ExplanationLanguage = ExplanationLanguage.ARABIC
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)


class FollowUpRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    subject_type: Literal["recommendation", "alert", "stock_qa"]
    subject_id: UUID | None = None
    prior_context: dict[str, Any] = Field(default_factory=dict)
    language: ExplanationLanguage = ExplanationLanguage.ARABIC
    thread_id: str = Field(min_length=1, max_length=128)


class StockQARequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    tickers: list[str] = Field(min_length=1, max_length=5)
    language: ExplanationLanguage = ExplanationLanguage.ARABIC
    thread_id: str | None = Field(default=None, min_length=1, max_length=128)
    max_tool_calls: int = Field(default=5, ge=1, le=10)

    @field_validator("tickers")
    @classmethod
    def normalize_tickers(cls, values: list[str]) -> list[str]:
        normalized = [value.strip().upper() for value in values if value.strip()]
        if not normalized:
            raise ValueError("at least one ticker is required")
        if len(set(normalized)) != len(normalized):
            raise ValueError("tickers must be unique")
        return normalized


class ExplanationResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = EXPLANATION_SCHEMA_VERSION
    status: Literal["ok", "partial", "not_found", "unavailable"] = "ok"
    explanation_type: Literal["recommendation", "alert", "follow_up"]
    ticker: str | None = None
    decision: RecommendationDecision | None = None
    summary: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    facts: list[str] = Field(default_factory=list)
    citations: list[EvidenceItem] = Field(default_factory=list, max_length=50)
    limitations: list[str] = Field(default_factory=list)
    disclaimer: str = Field(min_length=1)
    trace_id: UUID | None = None
    generated_at: datetime


class StockQAFact(BaseModel):
    label: str = Field(min_length=1, max_length=200)
    value: str = Field(min_length=1, max_length=1000)
    source_tool: str = Field(min_length=1, max_length=100)


class StockQAResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: str = EXPLANATION_SCHEMA_VERSION
    status: Literal["ok", "partial", "not_found", "unavailable"] = "ok"
    explanation_type: Literal["stock_qa"] = "stock_qa"
    tickers: list[str] = Field(min_length=1, max_length=5)
    data_date: date | None = None
    freshness_seconds: int | None = Field(default=None, ge=0)
    answer: str = Field(min_length=1)
    facts: list[StockQAFact] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    disclaimer: str = Field(min_length=1)
    trace_id: UUID | None = None
    generated_at: datetime
