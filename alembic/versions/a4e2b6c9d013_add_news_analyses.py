"""add versioned news analyses

Revision ID: a4e2b6c9d013
Revises: 0e3d7d98e421
Create Date: 2026-11-13

"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "a4e2b6c9d013"
down_revision: Union[str, Sequence[str], None] = "0e3d7d98e421"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "news_analyses",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("article_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("company_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("analysis_version", sa.String(length=50), nullable=False),
        sa.Column("schema_version", sa.String(length=50), nullable=False),
        sa.Column("model_provider", sa.String(length=100), nullable=True),
        sa.Column("model_name", sa.String(length=200), nullable=True),
        sa.Column("prompt_version", sa.String(length=50), nullable=False),
        sa.Column("taxonomy_version", sa.String(length=50), nullable=False),
        sa.Column("pipeline_version", sa.String(length=50), nullable=False),
        sa.Column("event_type", sa.String(length=50), nullable=False),
        sa.Column("direction", sa.String(length=20), nullable=False),
        sa.Column("relevance_score", sa.Float(), nullable=False),
        sa.Column("novelty_score", sa.Float(), nullable=False),
        sa.Column(
            "classification_confidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
        ),
        sa.Column("summary_ar", sa.Text(), nullable=True),
        sa.Column(
            "evidence_spans",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "requires_human_review",
            sa.Boolean(),
            server_default=sa.text("false"),
            nullable=False,
        ),
        sa.Column(
            "limitations",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
        sa.Column(
            "analyzed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.CheckConstraint(
            "direction IN ('positive', 'negative', 'neutral', 'unknown')",
            name="ck_news_analyses_direction",
        ),
        sa.CheckConstraint(
            "event_type IN ("
            "'earnings_results', 'revenue_or_profit_change', "
            "'dividend_announcement', 'capital_increase_or_rights_issue', "
            "'merger_acquisition_or_disposal', 'management_or_board_change', "
            "'regulatory_or_legal', 'trading_suspension_or_resumption', "
            "'material_contract_or_order', 'debt_or_financing', "
            "'ownership_or_major_shareholder', 'macroeconomic_or_sector', "
            "'analyst_opinion_or_forecast', 'rumor_or_unverified_claim', "
            "'routine_corporate_update', 'other', 'unknown')",
            name="ck_news_analyses_event_type",
        ),
        sa.CheckConstraint(
            "relevance_score >= 0 AND relevance_score <= 1",
            name="ck_news_analyses_relevance_range",
        ),
        sa.CheckConstraint(
            "novelty_score >= 0 AND novelty_score <= 1",
            name="ck_news_analyses_novelty_range",
        ),
        sa.ForeignKeyConstraint(
            ["article_id"],
            ["news_articles.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["company_id"],
            ["companies.id"],
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_news_analyses_article_analyzed_at",
        "news_analyses",
        ["article_id", "analyzed_at"],
        unique=False,
    )
    op.create_index(
        "ix_news_analyses_company_analyzed_at",
        "news_analyses",
        ["company_id", "analyzed_at"],
        unique=False,
    )
    op.create_index(
        "uq_news_analyses_article_company_version",
        "news_analyses",
        ["article_id", "company_id", "analysis_version"],
        unique=True,
        postgresql_where=sa.text("company_id IS NOT NULL"),
    )
    op.create_index(
        "uq_news_analyses_article_only_version",
        "news_analyses",
        ["article_id", "analysis_version"],
        unique=True,
        postgresql_where=sa.text("company_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(
        "uq_news_analyses_article_only_version",
        table_name="news_analyses",
    )
    op.drop_index(
        "uq_news_analyses_article_company_version",
        table_name="news_analyses",
    )
    op.drop_index(
        "ix_news_analyses_company_analyzed_at",
        table_name="news_analyses",
    )
    op.drop_index(
        "ix_news_analyses_article_analyzed_at",
        table_name="news_analyses",
    )
    op.drop_table("news_analyses")
