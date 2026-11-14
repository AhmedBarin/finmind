"""Contracts for the persisted structured-news-analysis tool."""

from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, model_validator

from app.news.schemas import NewsAnalysisRead
from app.news.analysis_schemas import StructuredNewsAnalysis


class AnalysisTaskMode(StrEnum):
    CLASSIFY = "classify"
    SUMMARIZE = "summarize"
    EXTRACT_FACTS = "extract_facts"
    RECHECK = "recheck"


class StructuredAnalysisRequest(BaseModel):
    article_ids: list[UUID] = Field(default_factory=list, max_length=5)
    permitted_text: str | None = Field(default=None, min_length=1, max_length=10000)
    company_id: UUID | None = None
    schema_version: str = Field(default="news-analysis-v1", pattern="^news-analysis-v1$")
    task_mode: AnalysisTaskMode = AnalysisTaskMode.CLASSIFY

    @model_validator(mode="after")
    def require_bounded_input(self) -> "StructuredAnalysisRequest":
        if bool(self.article_ids) == (self.permitted_text is not None):
            raise ValueError("provide article_ids or permitted_text, but not both")
        if self.permitted_text is not None:
            self.permitted_text = self.permitted_text.strip()
            if not self.permitted_text:
                raise ValueError("permitted_text must not be blank")
        return self


class StructuredAnalysisItem(BaseModel):
    article_id: UUID | None = None
    status: str
    analysis: NewsAnalysisRead | StructuredNewsAnalysis | None = None
    error: str | None = None


class StructuredAnalysisData(BaseModel):
    task_mode: AnalysisTaskMode
    items: list[StructuredAnalysisItem]
    limitations: list[str] = Field(default_factory=list)


class StructuredAnalysisResponse(BaseModel):
    status: str
    data: StructuredAnalysisData
    warnings: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    trace_id: UUID
    generated_at: str
