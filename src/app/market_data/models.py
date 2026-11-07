"""Persisted daily market prices."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from uuid import UUID, uuid4

from sqlalchemy import (
    BigInteger,
    Date,
    DateTime,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class StockPrice(Base):
    """One provider price row per ticker and trading date.

    Raw provider values are retained. Adjusted OHLC values are stored alongside
    them so indicators and Monitoring can use a consistent adjusted price series.
    """

    __tablename__ = "stock_prices"
    __table_args__ = (
        UniqueConstraint("ticker", "date", name="uq_stock_prices_ticker_date"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), primary_key=True, default=uuid4
    )
    ticker: Mapped[str] = mapped_column(String(20), nullable=False)
    date: Mapped[date] = mapped_column(Date, nullable=False)

    raw_open: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    raw_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    raw_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    raw_close: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))

    adj_open: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    adj_high: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    adj_low: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    adj_close: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))

    volume: Mapped[int | None] = mapped_column(BigInteger)
    dividends: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    stock_splits: Mapped[Decimal | None] = mapped_column(Numeric(18, 6))
    source: Mapped[str] = mapped_column(String(50), nullable=False)

    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )
