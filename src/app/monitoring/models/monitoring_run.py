from datetime import datetime
from uuid import UUID, uuid4

from sqlalchemy import DateTime, Integer, String, Text, func
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class MonitoringRun(Base):
    __tablename__ = "monitoring_runs"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="running",
        nullable=False,
    )
    rules_evaluated: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    rules_triggered: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    rules_skipped: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    rules_errored: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    error_message: Mapped[str | None] = mapped_column(Text)
