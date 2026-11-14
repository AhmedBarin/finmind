"""create investor profile, audit log, and learned preference tables

Revision ID: e8f1c2a9b401
Revises: e84b2cf61d39
Create Date: 2026-11-10
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "e8f1c2a9b401"
down_revision: Union[str, Sequence[str], None] = "e84b2cf61d39"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    """Create investor_profiles, profile_audit_logs, and learned_preferences."""
    op.create_table(
        "investor_profiles",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("risk_profile", sa.String(length=20), nullable=False),
        sa.Column("investment_horizon", sa.String(length=20), nullable=False),
        sa.Column("investment_goal", sa.String(length=30), nullable=False),
        sa.Column("investment_experience", sa.String(length=20), nullable=False),
        sa.Column("liquidity_floor_pct", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column("max_atr_pctl_cap", sa.Numeric(precision=5, scale=2), nullable=False),
        sa.Column(
            "excluded_sectors",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "excluded_tickers",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "preferred_sectors",
            postgresql.ARRAY(sa.Text()),
            server_default=sa.text("'{}'::text[]"),
            nullable=False,
        ),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default=sa.text("true"),
            nullable=False,
        ),
        sa.Column(
            "profile_version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "confirmed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "last_reviewed_at",
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
        sa.CheckConstraint(
            "risk_profile IN ('conservative', 'moderate', 'aggressive')",
            name="ck_investor_profiles_risk_profile",
        ),
        sa.CheckConstraint(
            "investment_horizon IN ('short', 'medium', 'long')",
            name="ck_investor_profiles_investment_horizon",
        ),
        sa.CheckConstraint(
            "investment_goal IN ('capital_preservation', 'growth', 'income', 'speculation')",
            name="ck_investor_profiles_investment_goal",
        ),
        sa.CheckConstraint(
            "investment_experience IN ('beginner', 'intermediate', 'advanced')",
            name="ck_investor_profiles_investment_experience",
        ),
        sa.CheckConstraint(
            "liquidity_floor_pct >= 0 AND liquidity_floor_pct <= 100",
            name="ck_investor_profiles_liquidity_floor_range",
        ),
        sa.CheckConstraint(
            "max_atr_pctl_cap >= 0 AND max_atr_pctl_cap <= 100",
            name="ck_investor_profiles_max_atr_cap_range",
        ),
        sa.CheckConstraint(
            "profile_version >= 1",
            name="ck_investor_profiles_version_positive",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_investor_profiles_user_id",
        "investor_profiles",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "uq_user_active_profile",
        "investor_profiles",
        ["user_id"],
        unique=True,
        postgresql_where=sa.text("is_active IS TRUE"),
    )

    op.create_table(
        "profile_audit_logs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("profile_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("change_type", sa.String(length=50), nullable=False),
        sa.Column("previous_state", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("new_state", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("changed_by", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint(
            "change_type IN ('initial_creation', 'user_edit', 're_profiling', 'preference_update')",
            name="ck_profile_audit_logs_change_type",
        ),
        sa.CheckConstraint(
            "changed_by IN ('user', 'admin', 'scheduled_review')",
            name="ck_profile_audit_logs_changed_by",
        ),
        sa.ForeignKeyConstraint(
            ["profile_id"],
            ["investor_profiles.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_profile_audit_logs_user_id",
        "profile_audit_logs",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_profile_audit_logs_profile_created",
        "profile_audit_logs",
        ["profile_id", "created_at"],
        unique=False,
    )

    op.create_table(
        "learned_preferences",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("preference_key", sa.String(length=100), nullable=False),
        sa.Column(
            "preference_value",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("confidence_score", sa.Numeric(precision=3, scale=2), nullable=False),
        sa.Column("source_event", sa.String(length=100), nullable=False),
        sa.Column(
            "user_validated",
            sa.Boolean(),
            server_default=sa.text("false"),
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
        sa.CheckConstraint(
            "confidence_score >= 0 AND confidence_score <= 1",
            name="ck_learned_preferences_confidence_range",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "preference_key", name="uq_user_preference_key"),
    )
    op.create_index(
        "ix_learned_preferences_user_id",
        "learned_preferences",
        ["user_id"],
        unique=False,
    )


def downgrade() -> None:
    """Drop learned_preferences, profile_audit_logs, and investor_profiles."""
    op.drop_index("ix_learned_preferences_user_id", table_name="learned_preferences")
    op.drop_table("learned_preferences")
    op.drop_index("ix_profile_audit_logs_profile_created", table_name="profile_audit_logs")
    op.drop_index("ix_profile_audit_logs_user_id", table_name="profile_audit_logs")
    op.drop_table("profile_audit_logs")
    op.drop_index("uq_user_active_profile", table_name="investor_profiles")
    op.drop_index("ix_investor_profiles_user_id", table_name="investor_profiles")
    op.drop_table("investor_profiles")

