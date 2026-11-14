"""create news signals

Revision ID: e84b2cf61d39
Revises: d53a17e8bc42
Create Date: 2026-11-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e84b2cf61d39"
down_revision: Union[str, Sequence[str], None] = "d53a17e8bc42"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_signals",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("as_of", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("signal_version", sa.String(50), nullable=False),
        sa.Column("aggregation_config_version", sa.String(50), nullable=False),
        sa.Column("input_hash", sa.String(64), nullable=False),
        sa.Column("direction", sa.String(20), nullable=False),
        sa.Column("article_count", sa.Integer(), nullable=False),
        sa.Column("eligible_article_count", sa.Integer(), nullable=False),
        sa.Column("coverage_status", sa.String(30), nullable=False),
        sa.Column("freshness_seconds", sa.Integer(), nullable=True),
        sa.Column("top_event_types", postgresql.JSONB(), server_default=sa.text("'{}'::jsonb"), nullable=False),
        sa.Column("contributing_article_ids", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("contributing_analysis_ids", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("reason_codes", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("limitations", postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.CheckConstraint("direction IN ('positive', 'negative', 'neutral', 'unknown')", name="ck_news_signals_direction"),
        sa.CheckConstraint("coverage_status IN ('available', 'no_relevant_news', 'stale', 'partial', 'unavailable')", name="ck_news_signals_coverage_status"),
        sa.CheckConstraint("article_count >= 0 AND eligible_article_count >= 0", name="ck_news_signals_nonnegative_counts"),
        sa.CheckConstraint("freshness_seconds IS NULL OR freshness_seconds >= 0", name="ck_news_signals_freshness_nonnegative"),
        sa.ForeignKeyConstraint(["company_id"], ["companies.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("company_id", "aggregation_config_version", "input_hash", name="uq_news_signals_company_config_input"),
    )
    op.create_index("ix_news_signals_company_as_of", "news_signals", ["company_id", "as_of"])


def downgrade() -> None:
    op.drop_index("ix_news_signals_company_as_of", table_name="news_signals")
    op.drop_table("news_signals")
