"""Market-data and evaluation schemas – Pydantic v2."""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel


class MarketDataPoint(BaseModel):
    ticker: str
    date: date
    open: float
    high: float
    low: float
    close: float
    volume: int
    updated_at: datetime


class TechnicalSignals(BaseModel):
    ticker: str
    date: date
    rsi: float | None = None
    sma_20: float | None = None
    sma_50: float | None = None
    atr: float | None = None
    composite_score: float | None = None
    calculated_at: datetime


class EvaluationResult(BaseModel):
    triggered: bool
    reason: str
    current_value: float | None = None
    threshold_value: float | None = None
    evidence: dict = {}
    error: bool = False
    error_message: str | None = None
