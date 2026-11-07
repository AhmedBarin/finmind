"""Persisted, reproducible technical-analysis snapshots."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    Float,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class TechnicalSnapshot(Base):
    """Technical outputs for one ticker/date/configuration version."""

    __tablename__ = "technical_snapshots"
    __table_args__ = (
        UniqueConstraint(
            "ticker",
            "date",
            "config_version",
            "input_hash",
            name="uq_technical_snapshots_ticker_date_config_input",
        ),
        CheckConstraint(
            "data_quality_status IN "
            "('valid', 'stale', 'insufficient_history', 'flagged')",
            name="ck_technical_snapshots_quality_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)
    calculated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    config_version: Mapped[str] = mapped_column(String(50), nullable=False)
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)

    # Scalar fields used by Monitoring. Its composite_score maps to setup_score.
    rsi: Mapped[float | None] = mapped_column(Float)
    sma_20: Mapped[float | None] = mapped_column(Float)
    sma_50: Mapped[float | None] = mapped_column(Float)
    atr: Mapped[float | None] = mapped_column(Float)
    setup_score: Mapped[float | None] = mapped_column(Float)

    regime: Mapped[str | None] = mapped_column(String(20))
    risk_label: Mapped[str | None] = mapped_column(String(20))
    data_quality_status: Mapped[str] = mapped_column(String(30), nullable=False)

    # Keep full calculation inputs/results for reproducibility and explanations.
    input_data: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    indicators: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    scores: Mapped[dict[str, Any]] = mapped_column(JSONB, default=dict, nullable=False)
    quality_flags: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
