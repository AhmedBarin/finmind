"""Contracts for Stock Q&A requests, tool results, LLM drafts and responses."""

from __future__ import annotations

import re
from datetime import date
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

TICKER_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9.-]{0,19}$")

ToolName = Literal[
    "get_technical_snapshot",
    "get_snapshot_history",
    "get_price_history",
    "compare_snapshots",
    "get_indicator_glossary",
]
PricePeriod = Literal["1w", "1m", "3m", "6m", "1y"]
FreshnessStatus = Literal["fresh", "stale", "missing"]
GenerationPath = Literal["llm", "llm_retry", "fallback", "no_data", "routed_only"]


class StockQARequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=1000)
    tickers: list[str] = Field(min_length=1, max_length=5)
    as_of: date | None = Field(
        default=None,
        description="Snapshot date to describe; defaults to the latest stored snapshot.",
    )
    period: PricePeriod = "1m"

    @field_validator("question")
    @classmethod
    def _strip_question(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("question must not be blank")
        return value

    @field_validator("tickers")
    @classmethod
    def _normalize_tickers(cls, values: list[str]) -> list[str]:
        normalized: list[str] = []
        for raw in values:
            ticker = raw.strip().upper()
            if not TICKER_RE.fullmatch(ticker):
                raise ValueError(f"invalid ticker: {raw!r}")
            if ticker not in normalized:
                normalized.append(ticker)
        return normalized


class ToolResult(BaseModel):
    """JSON-safe output of one read-only tool call."""

    tool: ToolName
    ticker: str | None = None
    data_date: date | None = None
    found: bool = True
    data: dict[str, Any] = Field(default_factory=dict)


class TickerFreshness(BaseModel):
    ticker: str
    data_date: date | None
    status: FreshnessStatus
    data_quality_status: str | None = None


class StockQAFact(BaseModel):
    model_config = ConfigDict(extra="forbid")

    ticker: str = Field(min_length=1, max_length=20)
    field: str = Field(min_length=1, max_length=100)
    value: float | str
    data_date: date | None = None


class StockQADraft(BaseModel):
    """The only part of the answer the LLM writes."""

    model_config = ConfigDict(extra="forbid")

    answer_ar: str = Field(min_length=1, max_length=4000)
    facts: list[StockQAFact] = Field(default_factory=list, max_length=50)
    limitations_ar: list[str] = Field(default_factory=list, max_length=20)


class StockQAResponse(BaseModel):
    explanation_type: Literal["stock_qa"] = "stock_qa"
    tickers: list[str]
    data_date: date | None = Field(
        description="Oldest snapshot date among the tickers that have data.",
    )
    answer_ar: str
    facts: list[StockQAFact]
    limitations_ar: list[str]
    disclaimer_ar: str
    freshness: list[TickerFreshness]
    routed_to_recommendation: list[str] = Field(
        default_factory=list,
        description="Question parts asking for advice; these belong to the Recommendation Engine.",
    )
    generation: GenerationPath
    tools_used: list[ToolName]
