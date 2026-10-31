from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FetchedArticle(BaseModel):
    """Normalized article data returned by a news source adapter."""

    model_config = ConfigDict(str_strip_whitespace=True)

    external_article_id: str | None = Field(default=None, max_length=200)
    source_url: str = Field(min_length=1, max_length=2000)
    canonical_url: str | None = Field(default=None, max_length=2000)
    title_original: str = Field(min_length=1)
    body_original: str | None = None
    language: str = Field(default="unknown", max_length=10)
    published_at: datetime | None = None
    updated_at_source: datetime | None = None
    author: str | None = None
    raw_metadata: dict[str, Any] = Field(default_factory=dict)


class NewsArticleRead(BaseModel):
    """Article fields returned by the news API."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    source_id: UUID
    external_article_id: str | None
    source_url: str
    canonical_url: str | None
    title_original: str
    title_normalized: str
    body_original: str | None
    body_cleaned: str | None
    body_excerpt: str | None
    language: str
    published_at: datetime | None
    updated_at_source: datetime | None
    author: str | None
    retrieved_at: datetime
    content_rights: str
    processing_status: str
    content_hash: str | None
    pipeline_version: str
    created_at: datetime
    updated_at: datetime