"""Typed contracts for document evidence and similar-news retrieval."""

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.agents.news_agent.schemas import ToolStatus


class RetrievalRequest(BaseModel):
    ticker: str | None = Field(default=None, min_length=1, max_length=20)
    company_id: UUID | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    limit: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def validate_scope_and_dates(self) -> "RetrievalRequest":
        if not self.ticker and self.company_id is None:
            raise ValueError("ticker or company_id is required")
        if self.ticker:
            self.ticker = self.ticker.strip().upper()
        for value in (self.start_at, self.end_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("timestamps must be timezone-aware")
        if self.start_at and self.end_at and self.start_at > self.end_at:
            raise ValueError("start_at must be before or equal to end_at")
        return self


class AnnualReportEvidenceRequest(RetrievalRequest):
    query: str = Field(min_length=1, max_length=500)
    fiscal_year: int | None = Field(default=None, ge=1900, le=2200)

    @model_validator(mode="after")
    def validate_query(self) -> "AnnualReportEvidenceRequest":
        self.query = self.query.strip()
        if not self.query:
            raise ValueError("query must not be blank")
        return self


class SimilarNewsRequest(BaseModel):
    query: str | None = Field(default=None, max_length=500)
    article_id: UUID | None = None
    ticker: str | None = Field(default=None, min_length=1, max_length=20)
    company_id: UUID | None = None
    start_at: datetime | None = None
    end_at: datetime | None = None
    event_types: list[str] = Field(default_factory=list, max_length=20)
    limit: int = Field(default=5, ge=1, le=10)

    @model_validator(mode="after")
    def validate_input(self) -> "SimilarNewsRequest":
        if not self.query and self.article_id is None:
            raise ValueError("query or article_id is required")
        if self.query:
            self.query = self.query.strip()
            if not self.query:
                raise ValueError("query must not be blank")
        if self.ticker:
            self.ticker = self.ticker.strip().upper()
        for value in (self.start_at, self.end_at):
            if value is not None and value.tzinfo is None:
                raise ValueError("timestamps must be timezone-aware")
        if self.start_at and self.end_at and self.start_at > self.end_at:
            raise ValueError("start_at must be before or equal to end_at")
        self.event_types = [value.strip().lower() for value in self.event_types if value.strip()]
        return self


class EvidenceItem(BaseModel):
    chunk_id: str
    article_id: UUID
    evidence_text: str
    source_url: str | None = None
    source_name: str | None = None
    document_title: str | None = None
    document_type: str | None = None
    publication_date: datetime | None = None
    fiscal_year: int | None = None
    page: int | None = None
    section: str | None = None
    retrieval_score: float | None = None


class SimilarNewsItem(BaseModel):
    article_id: UUID
    source_url: str | None = None
    source_name: str | None = None
    published_at: datetime | None = None
    event_type: str | None = None
    similarity_score: float = Field(ge=0)
    evidence_text: str


class RetrievalData(BaseModel):
    items: list[EvidenceItem | SimilarNewsItem] = Field(default_factory=list)
    coverage_status: str
    limitations: list[str] = Field(default_factory=list)


class RetrievalToolResponse(BaseModel):
    status: ToolStatus
    data: RetrievalData
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    trace_id: UUID
    generated_at: datetime
