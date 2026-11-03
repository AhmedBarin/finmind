from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import DateTime, ForeignKey, Integer, text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MonitoringRuleState(Base):
    __tablename__ = "monitoring_rule_states"

    rule_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("monitoring_rules.id"),
        primary_key=True,
        unique=True,
    )
    last_evaluated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    last_value: Mapped[float | None] = mapped_column()
    last_threshold_value: Mapped[float | None] = mapped_column()
    last_triggered: Mapped[bool | None] = mapped_column()
    consecutive_triggers: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    state_data: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
