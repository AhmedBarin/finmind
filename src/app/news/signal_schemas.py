"""Contracts for deterministic company-level news signal aggregation."""

from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class NewsCoverageStatus(StrEnum):
    AVAILABLE = "available"
    NO_RELEVANT_NEWS = "no_relevant_news"
    STALE = "stale"
    PARTIAL = "partial"
    UNAVAILABLE = "unavailable"


@dataclass(frozen=True)
class NewsSignalAggregationConfig:
    version: str = "news-signal-v1"
    lookback: timedelta = timedelta(days=7)
    source_freshness: timedelta = timedelta(hours=24)
    min_relevance: float = 0.5


class NewsSignalRead(BaseModel):
    """Stored news-side signal with transparent provenance and no score."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    company_id: UUID
    as_of: datetime
    window_start: datetime
    window_end: datetime
    signal_version: str
    aggregation_config_version: str
    direction: str
    article_count: int = Field(ge=0)
    eligible_article_count: int = Field(ge=0)
    coverage_status: NewsCoverageStatus
    freshness_seconds: int | None = Field(default=None, ge=0)
    top_event_types: dict[str, int]
    contributing_article_ids: list[str]
    contributing_analysis_ids: list[str]
    reason_codes: list[str]
    limitations: list[str]
