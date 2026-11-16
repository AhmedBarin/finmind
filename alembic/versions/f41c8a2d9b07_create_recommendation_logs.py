"""create recommendation audit log

Revision ID: f41c8a2d9b07
Revises: e8f1c2a9b401
Create Date: 2026-11-16
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f41c8a2d9b07"
down_revision: Union[str, Sequence[str], None] = "e8f1c2a9b401"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "recommendation_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("ticker", sa.String(length=32), nullable=False),
        sa.Column("trading_date", sa.Date(), nullable=True),
        sa.Column("snapshot_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("config_version", sa.String(length=50), nullable=False),
        sa.Column("decision", sa.String(length=32), nullable=False),
        sa.Column(
            "blockers",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column("confidence", sa.String(length=12), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "decision IN ('BUY', 'WATCH', 'AVOID', 'EXCLUDED', 'NO_RECOMMENDATION')",
            name="ck_recommendation_logs_decision",
        ),
        sa.CheckConstraint(
            "confidence IN ('High', 'Medium', 'Low')",
            name="ck_recommendation_logs_confidence",
        ),
        sa.ForeignKeyConstraint(
            ["snapshot_id"],
            ["technical_snapshots.id"],
            name="fk_recommendation_logs_snapshot_id_technical_snapshots",
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_recommendation_logs_user_created",
        "recommendation_logs",
        ["user_id", "created_at"],
    )
    op.create_index(
        "ix_recommendation_logs_user_ticker_date",
        "recommendation_logs",
        ["user_id", "ticker", "trading_date"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_recommendation_logs_user_ticker_date",
        table_name="recommendation_logs",
    )
    op.drop_index(
        "ix_recommendation_logs_user_created",
        table_name="recommendation_logs",
    )
    op.drop_table("recommendation_logs")
