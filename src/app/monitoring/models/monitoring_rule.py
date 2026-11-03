from datetime import datetime
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Index, Integer, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MonitoringRule(Base):
    __tablename__ = "monitoring_rules"
    __table_args__ = (
        Index("ix_monitoring_rules_user_id", "user_id"),
        Index("ix_monitoring_rules_ticker", "ticker"),
        Index("ix_monitoring_rules_is_active", "is_active"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    rule_type: Mapped[str] = mapped_column(String(50), nullable=False)
    parameters: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    is_active: Mapped[bool] = mapped_column(
        default=True,
        nullable=False,
    )
    cooldown_minutes: Mapped[int] = mapped_column(
        Integer,
        default=60,
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
    deactivated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
