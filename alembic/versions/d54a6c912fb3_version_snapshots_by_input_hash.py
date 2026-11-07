"""version technical snapshots by input hash

Revision ID: d54a6c912fb3
Revises: c7d9a4b1e203
Create Date: 2026-11-07
"""

from alembic import op
import sqlalchemy as sa


revision = "d54a6c912fb3"
down_revision = "c7d9a4b1e203"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "technical_snapshots",
        sa.Column("input_hash", sa.String(length=64), nullable=True),
    )
    op.execute(
        "UPDATE technical_snapshots "
        "SET input_hash = md5(id::text) WHERE input_hash IS NULL"
    )
    op.alter_column("technical_snapshots", "input_hash", nullable=False)
    op.drop_constraint(
        "uq_technical_snapshots_ticker_date_config",
        "technical_snapshots",
        type_="unique",
    )
    op.create_unique_constraint(
        "uq_technical_snapshots_ticker_date_config_input",
        "technical_snapshots",
        ["ticker", "date", "config_version", "input_hash"],
    )


def downgrade() -> None:
    connection = op.get_bind()
    duplicate_versions = connection.scalar(
        sa.text(
            "SELECT EXISTS ("
            "SELECT 1 FROM technical_snapshots "
            "GROUP BY ticker, date, config_version HAVING COUNT(*) > 1"
            ")"
        )
    )
    if duplicate_versions:
        raise RuntimeError(
            "Cannot downgrade while multiple input versions exist for a "
            "ticker/date/config version. Preserve or export those snapshots first."
        )

    op.drop_constraint(
        "uq_technical_snapshots_ticker_date_config_input",
        "technical_snapshots",
        type_="unique",
    )
    op.drop_column("technical_snapshots", "input_hash")
    op.create_unique_constraint(
        "uq_technical_snapshots_ticker_date_config",
        "technical_snapshots",
        ["ticker", "date", "config_version"],
    )
