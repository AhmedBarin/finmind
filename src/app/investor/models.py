"""SQLAlchemy 2.x ORM models for the Investor Agent."""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.investor.schemas import (
    AuditChangedBy,
    InvestmentExperience,
    InvestmentGoal,
    InvestmentHorizon,
    ProfileAuditChangeType,
    RiskProfile,
)


def _enum_sql_list(enum_cls: type) -> str:
    return ", ".join(f"'{member.value}'" for member in enum_cls)


class InvestorProfile(Base):
    """Confirmed investor profile and derived gating thresholds.

    ``user_id`` omits a foreign key to ``users.id`` until the shared authentication
    table is introduced, matching ``monitoring_rules`` and ``alerts``.
    """

    __tablename__ = "investor_profiles"
    __table_args__ = (
        Index("ix_investor_profiles_user_id", "user_id"),
        # Partial unique index allows unlimited archived (is_active=false)
        # versions while enforcing at most one active profile per user.
        Index(
            "uq_user_active_profile",
            "user_id",
            unique=True,
            postgresql_where=text("is_active IS TRUE"),
        ),
        CheckConstraint(
            f"risk_profile IN ({_enum_sql_list(RiskProfile)})",
            name="ck_investor_profiles_risk_profile",
        ),
        CheckConstraint(
            f"investment_horizon IN ({_enum_sql_list(InvestmentHorizon)})",
            name="ck_investor_profiles_investment_horizon",
        ),
        CheckConstraint(
            f"investment_goal IN ({_enum_sql_list(InvestmentGoal)})",
            name="ck_investor_profiles_investment_goal",
        ),
        CheckConstraint(
            f"investment_experience IN ({_enum_sql_list(InvestmentExperience)})",
            name="ck_investor_profiles_investment_experience",
        ),
        CheckConstraint(
            "liquidity_floor_pct >= 0 AND liquidity_floor_pct <= 100",
            name="ck_investor_profiles_liquidity_floor_range",
        ),
        CheckConstraint(
            "max_atr_pctl_cap >= 0 AND max_atr_pctl_cap <= 100",
            name="ck_investor_profiles_max_atr_cap_range",
        ),
        CheckConstraint(
            "profile_version >= 1",
            name="ck_investor_profiles_version_positive",
        ),
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
    risk_profile: Mapped[str] = mapped_column(String(20), nullable=False)
    investment_horizon: Mapped[str] = mapped_column(String(20), nullable=False)
    investment_goal: Mapped[str] = mapped_column(String(30), nullable=False)
    investment_experience: Mapped[str] = mapped_column(String(20), nullable=False)

    liquidity_floor_pct: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
    )
    max_atr_pctl_cap: Mapped[Decimal] = mapped_column(
        Numeric(5, 2),
        nullable=False,
    )

    excluded_sectors: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        default=list,
        server_default=text("'{}'::text[]"),
        nullable=False,
    )
    excluded_tickers: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        default=list,
        server_default=text("'{}'::text[]"),
        nullable=False,
    )
    preferred_sectors: Mapped[list[str]] = mapped_column(
        ARRAY(Text),
        default=list,
        server_default=text("'{}'::text[]"),
        nullable=False,
    )

    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
        nullable=False,
    )
    profile_version: Mapped[int] = mapped_column(
        Integer,
        default=1,
        server_default=text("1"),
        nullable=False,
    )
    confirmed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    last_reviewed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
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


class ProfileAuditLog(Base):
    """Immutable audit trail for confirmed investor profile changes."""

    __tablename__ = "profile_audit_logs"
    __table_args__ = (
        Index("ix_profile_audit_logs_user_id", "user_id"),
        Index(
            "ix_profile_audit_logs_profile_created",
            "profile_id",
            "created_at",
        ),
        CheckConstraint(
            f"change_type IN ({_enum_sql_list(ProfileAuditChangeType)})",
            name="ck_profile_audit_logs_change_type",
        ),
        CheckConstraint(
            f"changed_by IN ({_enum_sql_list(AuditChangedBy)})",
            name="ck_profile_audit_logs_changed_by",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    profile_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("investor_profiles.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        nullable=False,
    )
    change_type: Mapped[str] = mapped_column(String(50), nullable=False)
    previous_state: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    new_state: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    changed_by: Mapped[str] = mapped_column(String(50), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class LearnedPreference(Base):
    """Long-term learned investor preferences (isolated from active risk gates)."""

    __tablename__ = "learned_preferences"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "preference_key",
            name="uq_user_preference_key",
        ),
        Index("ix_learned_preferences_user_id", "user_id"),
        CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="ck_learned_preferences_confidence_range",
        ),
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
    preference_key: Mapped[str] = mapped_column(String(100), nullable=False)
    preference_value: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        nullable=False,
    )
    confidence_score: Mapped[Decimal] = mapped_column(
        Numeric(3, 2),
        nullable=False,
    )
    source_event: Mapped[str] = mapped_column(String(100), nullable=False)
    user_validated: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
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

