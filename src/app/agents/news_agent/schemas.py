"""Strict, bounded contracts for the first News Agent tools."""

from datetime import datetime, timedelta, timezone
from enum import StrEnum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class ToolStatus(StrEnum):
    OK = "ok"
    PARTIAL = "partial"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"
    INVALID_REQUEST = "invalid_request"
    FAILED = "failed"


class NewsToolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tickers: list[str] = Field(default_factory=list, max_length=20)
    company_id: UUID | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    event_types: list[str] = Field(default_factory=list, max_length=20)
    sentiments: list[str] = Field(default_factory=list, max_length=4)
    directions: list[str] = Field(default_factory=list, max_length=4)
    source_types: list[str] = Field(default_factory=list, max_length=10)
    language: str | None = Field(default=None, pattern="^(ar|en|mixed)$")
    limit: int = Field(default=20, ge=1, le=20)

    @field_validator("tickers")
    @classmethod
    def normalize_values(cls, values: list[str]) -> list[str]:
        return [value.strip().upper() for value in values if value.strip()]

    @field_validator("event_types", "sentiments", "directions", "source_types")
    @classmethod
    def normalize_filters(cls, values: list[str]) -> list[str]:
        return [value.strip().lower() for value in values if value.strip()]

    @field_validator("start_at", "end_at")
    @classmethod
    def require_timezone(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("timestamps must be timezone-aware")
        return value

    @model_validator(mode="after")
    def validate_dates(self) -> "NewsToolRequest":
        if self.start_at and self.end_at and self.start_at > self.end_at:
            raise ValueError("start_at must be before or equal to end_at")
        return self

    @model_validator(mode="after")
    def validate_direction_filters(self) -> "NewsToolRequest":
        values = [*self.sentiments, *self.directions]
        invalid = set(values) - {"positive", "negative", "neutral", "unknown"}
        if invalid:
            raise ValueError(f"unsupported direction filter: {sorted(invalid)}")
        self.directions = list(dict.fromkeys(values))
        return self


class SearchNewsRequest(NewsToolRequest):
    query: str = Field(min_length=1, max_length=500)

    @field_validator("query")
    @classmethod
    def normalize_query(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("query must not be blank")
        return value


class RecentNewsRequest(NewsToolRequest):
    lookback_hours: int = Field(default=24, ge=1, le=24 * 30)

    @model_validator(mode="after")
    def require_company_scope(self) -> "RecentNewsRequest":
        if not self.tickers and self.company_id is None:
            raise ValueError("ticker or company_id is required")
        if self.start_at is None and self.end_at is None:
            self.end_at = datetime.now(timezone.utc)
            self.start_at = self.end_at - timedelta(hours=self.lookback_hours)
        elif self.start_at is None:
            self.start_at = self.end_at - timedelta(hours=self.lookback_hours)
        elif self.end_at is None:
            self.end_at = self.start_at + timedelta(hours=self.lookback_hours)
        return self


class CompanyNewsRequest(NewsToolRequest):
    ticker: str | None = Field(default=None, min_length=1, max_length=20)

    @model_validator(mode="after")
    def require_company_scope(self) -> "CompanyNewsRequest":
        if not self.ticker and self.company_id is None:
            raise ValueError("ticker or company_id is required")
        if self.ticker:
            self.ticker = self.ticker.strip().upper()
        return self


class NewsToolArticle(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    article_id: UUID
    title: str
    published_at: datetime | None
    source_name: str
    source_type: str
    source_url: str
    language: str
    content_rights: str
    snippet: str | None = None
    relevance_score: float | None = Field(default=None, ge=0, le=1)
    ticker_links: list[str] = Field(default_factory=list)
    link_confidence: list[float] = Field(default_factory=list)
    direction: str | None = None
    event_type: str | None = None
    analysis_status: str = "not_analyzed"
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    duplicate_content: bool = False


class NewsToolData(BaseModel):
    articles: list[NewsToolArticle] = Field(default_factory=list)
    coverage_status: str = "available"
    freshness_seconds: int | None = Field(default=None, ge=0)


class ToolResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: ToolStatus
    data: NewsToolData
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    trace_id: UUID
    generated_at: datetime
