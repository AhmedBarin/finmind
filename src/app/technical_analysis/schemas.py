"""Read-only API contracts for technical snapshots and market prices."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, computed_field


DataQualityStatus = Literal["valid", "stale", "insufficient_history", "flagged"]
TECHNICAL_API_SCHEMA_VERSION = "technical-snapshot.v1"


class TechnicalSnapshotRead(BaseModel):
    """A persisted technical result, including quality and reproducibility data."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ticker: str
    date: date
    calculated_at: datetime
    config_version: str
    input_hash: str
    data_quality_status: DataQualityStatus
    rsi: float | None
    sma_20: float | None
    sma_50: float | None
    atr: float | None
    setup_score: float | None
    regime: str | None
    risk_label: str | None
    input_data: dict[str, Any] = Field(default_factory=dict)
    indicators: dict[str, Any] = Field(default_factory=dict)
    scores: dict[str, Any] = Field(default_factory=dict)
    quality_flags: list[str] = Field(default_factory=list)

    @computed_field
    @property
    def schema_version(self) -> str:
        return TECHNICAL_API_SCHEMA_VERSION

    @computed_field
    @property
    def provenance(self) -> dict[str, str]:
        return {
            "source_table": "technical_snapshots",
            "config_version": self.config_version,
            "input_hash": self.input_hash,
        }


class TechnicalSnapshotHistoryRead(BaseModel):
    schema_version: str = TECHNICAL_API_SCHEMA_VERSION
    ticker: str
    from_date: date | None
    to_date: date | None
    count: int
    snapshots: list[TechnicalSnapshotRead]


class TechnicalSnapshotComparisonRead(BaseModel):
    schema_version: str = TECHNICAL_API_SCHEMA_VERSION
    ticker: str
    first: TechnicalSnapshotRead | None
    second: TechnicalSnapshotRead | None


class StockPriceRead(BaseModel):
    """One stored market-price row; raw and adjusted values stay distinct."""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    ticker: str
    date: date
    raw_open: Decimal | None
    raw_high: Decimal | None
    raw_low: Decimal | None
    raw_close: Decimal | None
    adj_open: Decimal | None
    adj_high: Decimal | None
    adj_low: Decimal | None
    adj_close: Decimal | None
    volume: int | None
    dividends: Decimal | None
    stock_splits: Decimal | None
    source: str
    fetched_at: datetime
    created_at: datetime
    updated_at: datetime


class StockPriceHistoryRead(BaseModel):
    schema_version: str = TECHNICAL_API_SCHEMA_VERSION
    ticker: str
    from_date: date | None
    to_date: date | None
    count: int
    prices: list[StockPriceRead]
