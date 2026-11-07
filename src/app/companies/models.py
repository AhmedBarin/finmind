from datetime import date, datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class Company(Base):
    """Canonical company identity shared by FinMind modules."""

    __tablename__ = "companies"
    __table_args__ = (
        UniqueConstraint(
            "exchange",
            "ticker",
            name="uq_companies_exchange_ticker",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    exchange: Mapped[str] = mapped_column(
        String(20),
        default="EGX",
        server_default="EGX",
        nullable=False,
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    name_en: Mapped[str] = mapped_column(String(200), nullable=False)
    name_ar: Mapped[Optional[str]] = mapped_column(String(200))
    sector: Mapped[Optional[str]] = mapped_column(String(100))
    is_active: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        server_default=text("true"),
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


class CompanyAlias(Base):
    """A verified or pending name that can refer to a canonical company."""

    __tablename__ = "company_aliases"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "alias_normalized",
            name="uq_company_aliases_company_normalized",
        ),
        Index("ix_company_aliases_alias_normalized", "alias_normalized"),
        CheckConstraint(
            "alias_type IN "
            "('legal_name', 'short_name', 'ticker', "
            "'transliteration', 'former_name', 'other')",
            name="ck_company_aliases_alias_type",
        ),
        CheckConstraint(
            "verification_status IN ('pending', 'verified', 'rejected')",
            name="ck_company_aliases_verification_status",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    alias_text: Mapped[str] = mapped_column(String(300), nullable=False)
    alias_normalized: Mapped[str] = mapped_column(String(300), nullable=False)
    language: Mapped[str] = mapped_column(
        String(10),
        default="unknown",
        server_default="unknown",
        nullable=False,
    )
    alias_type: Mapped[str] = mapped_column(
        String(30),
        default="other",
        server_default="other",
        nullable=False,
    )
    valid_from: Mapped[Optional[date]] = mapped_column(Date)
    valid_to: Mapped[Optional[date]] = mapped_column(Date)
    verification_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        nullable=False,
    )
    verified_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
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