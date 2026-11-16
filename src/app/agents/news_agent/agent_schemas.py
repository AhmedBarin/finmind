"""HTTP contracts for the LangChain-backed News Agent."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class NewsAgentRequest(BaseModel):
    message: str = Field(min_length=1, max_length=4000)
    language: str = Field(default="ar", pattern="^(ar|en)$")
    max_tool_calls: int = Field(default=3, ge=1, le=6)


class NewsAgentResponse(BaseModel):
    status: str
    answer: str
    citations: list[dict[str, Any]] = Field(default_factory=list)
    coverage_status: str | None = None
    warnings: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    trace_id: UUID
    generated_at: datetime
