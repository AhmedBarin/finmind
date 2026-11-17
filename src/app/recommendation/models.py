"""Database model for recommendation audit records."""

from __future__ import annotations

from datetime import date, datetime
from uuid import UUID, uuid4

from sqlalchemy import (
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class RecommendationLog(Base):
    """Immutable record of a recommendation decision for audit/history."""

    __tablename__ = "recommendation_logs"
    __table_args__ = (
        CheckConstraint(
            "decision IN ('BUY', 'WATCH', 'AVOID', 'EXCLUDED', 'NO_RECOMMENDATION')",
            name="ck_recommendation_logs_decision",
        ),
        CheckConstraint(
            "confidence IN ('High', 'Medium', 'Low')",
            name="ck_recommendation_logs_confidence",
        ),
        Index(
            "ix_recommendation_logs_user_created",
            "user_id",
            "created_at",
        ),
        Index(
            "ix_recommendation_logs_user_ticker_date",
            "user_id",
            "ticker",
            "trading_date",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    user_id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), nullable=False)
    ticker: Mapped[str] = mapped_column(String(32), nullable=False)
    trading_date: Mapped[date | None] = mapped_column(Date)
    snapshot_id: Mapped[UUID | None] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("technical_snapshots.id", ondelete="SET NULL"),
    )
    config_version: Mapped[str] = mapped_column(String(50), nullable=False)
    decision: Mapped[str] = mapped_column(String(32), nullable=False)
    blockers: Mapped[list[str]] = mapped_column(JSONB, default=list, nullable=False)
    confidence: Mapped[str] = mapped_column(String(12), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
