"""store official EGX holidays and explicit calendar coverage

Revision ID: a61b9f74c205
Revises: f41c8a2d9b07
Create Date: 2026-11-24
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a61b9f74c205"
down_revision: Union[str, Sequence[str], None] = "f41c8a2d9b07"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "egx_calendar_coverage",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("coverage_start", sa.Date(), nullable=False),
        sa.Column("verified_through", sa.Date(), nullable=False),
        sa.Column("verification_reference_url", sa.String(length=2048), nullable=False),
        sa.Column(
            "verified_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "verified_through >= coverage_start",
            name="ck_egx_calendar_coverage_verified_range",
        ),
        sa.UniqueConstraint("coverage_start", name="uq_egx_calendar_coverage_start"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_egx_calendar_coverage_range",
        "egx_calendar_coverage",
        ["coverage_start", "verified_through"],
    )
    op.create_table(
        "egx_market_holidays",
        sa.Column("holiday_date", sa.Date(), nullable=False),
        sa.Column("holiday_name", sa.String(length=200), nullable=False),
        sa.Column("announcement_url", sa.String(length=2048), nullable=False),
        sa.Column("announcement_published_at", sa.Date(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("holiday_date"),
    )


def downgrade() -> None:
    op.drop_table("egx_market_holidays")
    op.drop_index(
        "ix_egx_calendar_coverage_range",
        table_name="egx_calendar_coverage",
    )
    op.drop_table("egx_calendar_coverage")
