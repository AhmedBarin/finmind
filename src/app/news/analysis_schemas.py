"""Versioned, validated contract for LLM-produced news analysis."""

from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class NewsSentiment(StrEnum):
    """Tone toward the identified company or event, separate from materiality."""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"
    MIXED = "mixed"
    UNKNOWN = "unknown"


class NewsDirectionLevel(StrEnum):
    """Estimated materiality of the event; not its positive/negative tone."""

    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"
    UNKNOWN = "unknown"


class NewsEventType(StrEnum):
    """Initial event taxonomy from the unified implementation specification."""

    EARNINGS_RESULTS = "earnings_results"
    REVENUE_OR_PROFIT_CHANGE = "revenue_or_profit_change"
    DIVIDEND_ANNOUNCEMENT = "dividend_announcement"
    CAPITAL_INCREASE_OR_RIGHTS_ISSUE = "capital_increase_or_rights_issue"
    MERGER_ACQUISITION_OR_DISPOSAL = "merger_acquisition_or_disposal"
    MANAGEMENT_OR_BOARD_CHANGE = "management_or_board_change"
    REGULATORY_OR_LEGAL = "regulatory_or_legal"
    TRADING_SUSPENSION_OR_RESUMPTION = "trading_suspension_or_resumption"
    MATERIAL_CONTRACT_OR_ORDER = "material_contract_or_order"
    DEBT_OR_FINANCING = "debt_or_financing"
    OWNERSHIP_OR_MAJOR_SHAREHOLDER = "ownership_or_major_shareholder"
    MACROECONOMIC_OR_SECTOR = "macroeconomic_or_sector"
    ANALYST_OPINION_OR_FORECAST = "analyst_opinion_or_forecast"
    RUMOR_OR_UNVERIFIED_CLAIM = "rumor_or_unverified_claim"
    ROUTINE_CORPORATE_UPDATE = "routine_corporate_update"
    OTHER = "other"
    UNKNOWN = "unknown"


class EvidenceSourceField(StrEnum):
    TITLE_ORIGINAL = "title_original"
    BODY_ORIGINAL = "body_original"
    BODY_CLEANED = "body_cleaned"
    BODY_EXCERPT = "body_excerpt"


class NewsFieldConfidence(BaseModel):
    """Confidence for each extraction dimension, not one blended score."""

    model_config = ConfigDict(extra="forbid")

    event_type: float = Field(ge=0.0, le=1.0)
    sentiment: float = Field(ge=0.0, le=1.0)
    direction_level: float = Field(ge=0.0, le=1.0)
    relevance: float = Field(ge=0.0, le=1.0)
    novelty: float = Field(ge=0.0, le=1.0)


class NewsEvidenceSpan(BaseModel):
    """An exact source quote that supports an analysis claim."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    claim: str = Field(min_length=1, max_length=500)
    quote: str = Field(min_length=1, max_length=2000)
    source_field: EvidenceSourceField
    start_char: int | None = Field(default=None, ge=0)
    end_char: int | None = Field(default=None, ge=0)

    @model_validator(mode="after")
    def offsets_must_be_a_valid_pair(self) -> "NewsEvidenceSpan":
        if (self.start_char is None) != (self.end_char is None):
            raise ValueError("start_char and end_char must both be set or both be null")
        if self.start_char is not None and self.end_char <= self.start_char:
            raise ValueError("end_char must be greater than start_char")
        return self


class StructuredNewsAnalysis(BaseModel):
    """LLM output contract; article and model identity are supplied by the caller."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    schema_version: Literal["news-analysis-v1"] = "news-analysis-v1"
    event_type: NewsEventType
    sentiment: NewsSentiment
    direction_level: NewsDirectionLevel
    relevance_score: float = Field(ge=0.0, le=1.0)
    novelty_score: float = Field(ge=0.0, le=1.0)
    confidence: NewsFieldConfidence
    summary_ar: str | None = Field(default=None, max_length=2000)
    summary_en: str | None = Field(default=None, max_length=2000)
    evidence_spans: list[NewsEvidenceSpan] = Field(default_factory=list, max_length=20)
    requires_human_review: bool = False
    limitations: list[str] = Field(default_factory=list, max_length=20)

    @model_validator(mode="after")
    def enforce_evidence_and_review_rules(self) -> "StructuredNewsAnalysis":
        if (
            self.sentiment == NewsSentiment.UNKNOWN
            or self.direction_level == NewsDirectionLevel.UNKNOWN
        ) and not self.requires_human_review:
            raise ValueError("unknown classification must be flagged for human review")
        if (
            self.sentiment not in {NewsSentiment.UNKNOWN, NewsSentiment.MIXED}
            and not self.evidence_spans
        ):
            raise ValueError("a classified sentiment requires at least one evidence span")
        return self


def validate_evidence_against_article(
    analysis: StructuredNewsAnalysis,
    *,
    title_original: str,
    body_original: str | None,
    body_cleaned: str | None,
    body_excerpt: str | None,
) -> None:
    """Reject evidence quotes that do not occur at the claimed source location."""

    article_fields = {
        EvidenceSourceField.TITLE_ORIGINAL: title_original,
        EvidenceSourceField.BODY_ORIGINAL: body_original,
        EvidenceSourceField.BODY_CLEANED: body_cleaned,
        EvidenceSourceField.BODY_EXCERPT: body_excerpt,
    }

    for span in analysis.evidence_spans:
        source_text = article_fields[span.source_field]
        if not source_text:
            raise ValueError(
                f"evidence source {span.source_field.value} is empty or unavailable"
            )

        if span.start_char is None:
            if span.quote not in source_text:
                raise ValueError(
                    "evidence quote does not occur in the referenced article field"
                )
        elif source_text[span.start_char : span.end_char] != span.quote:
            raise ValueError("evidence quote does not match the referenced article offsets")
