"""add market prices and technical snapshots

Revision ID: c7d9a4b1e203
Revises: b16e162cf1ba
Create Date: 2026-11-07
"""

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "c7d9a4b1e203"
down_revision = "b16e162cf1ba"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "stock_prices",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("raw_open", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("raw_high", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("raw_low", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("raw_close", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("adj_open", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("adj_high", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("adj_low", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("adj_close", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("volume", sa.BigInteger(), nullable=True),
        sa.Column("dividends", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("stock_splits", sa.Numeric(precision=18, scale=6), nullable=True),
        sa.Column("source", sa.String(length=50), nullable=False),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ticker", "date", name="uq_stock_prices_ticker_date"
        ),
    )

    op.create_table(
        "technical_snapshots",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticker", sa.String(length=20), nullable=False),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column(
            "calculated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("config_version", sa.String(length=50), nullable=False),
        sa.Column("rsi", sa.Float(), nullable=True),
        sa.Column("sma_20", sa.Float(), nullable=True),
        sa.Column("sma_50", sa.Float(), nullable=True),
        sa.Column("atr", sa.Float(), nullable=True),
        sa.Column("setup_score", sa.Float(), nullable=True),
        sa.Column("regime", sa.String(length=20), nullable=True),
        sa.Column("risk_label", sa.String(length=20), nullable=True),
        sa.Column("data_quality_status", sa.String(length=30), nullable=False),
        sa.Column("input_data", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("indicators", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("scores", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("quality_flags", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.CheckConstraint(
            "data_quality_status IN "
            "('valid', 'stale', 'insufficient_history', 'flagged')",
            name="ck_technical_snapshots_quality_status",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "ticker",
            "date",
            "config_version",
            name="uq_technical_snapshots_ticker_date_config",
        ),
    )


def downgrade() -> None:
    op.drop_table("technical_snapshots")
    op.drop_table("stock_prices")
