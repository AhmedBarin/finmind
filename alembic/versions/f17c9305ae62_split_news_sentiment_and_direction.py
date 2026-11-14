"""split news sentiment and direction level

Revision ID: f17c9305ae62
Revises: a4e2b6c9d013
Create Date: 2026-11-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "f17c9305ae62"
down_revision: Union[str, Sequence[str], None] = "a4e2b6c9d013"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_news_analyses_direction",
        "news_analyses",
        type_="check",
    )
    op.alter_column(
        "news_analyses",
        "direction",
        new_column_name="sentiment",
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_news_analyses_sentiment",
        "news_analyses",
        "sentiment IN ('positive', 'neutral', 'negative', 'mixed', 'unknown')",
    )

    op.add_column(
        "news_analyses",
        sa.Column(
            "sentiment_score",
            sa.Float(),
            nullable=True,
        ),
    )
    op.add_column(
        "news_analyses",
        sa.Column(
            "direction_level",
            sa.String(length=20),
            server_default="unknown",
            nullable=False,
        ),
    )
    op.add_column(
        "news_analyses",
        sa.Column("source_reliability", sa.Float(), nullable=True),
    )
    op.add_column(
        "news_analyses",
        sa.Column("summary_en", sa.Text(), nullable=True),
    )
    op.add_column(
        "news_analyses",
        sa.Column(
            "key_facts",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "news_analyses",
        sa.Column(
            "contradictions",
            postgresql.JSONB(astext_type=sa.Text()),
            server_default=sa.text("'[]'::jsonb"),
            nullable=False,
        ),
    )
    op.add_column(
        "news_analyses",
        sa.Column(
            "review_status",
            sa.String(length=20),
            server_default="pending",
            nullable=False,
        ),
    )

    op.execute(
        "UPDATE news_analyses SET requires_human_review = true, "
        "review_status = 'pending'"
    )
    op.create_check_constraint(
        "ck_news_analyses_direction_level",
        "news_analyses",
        "direction_level IN ('low', 'medium', 'high', 'critical', 'unknown')",
    )
    op.create_check_constraint(
        "ck_news_analyses_sentiment_score_range",
        "news_analyses",
        "sentiment_score IS NULL OR (sentiment_score >= -1 AND sentiment_score <= 1)",
    )
    op.create_check_constraint(
        "ck_news_analyses_source_reliability_range",
        "news_analyses",
        "source_reliability IS NULL OR "
        "(source_reliability >= 0 AND source_reliability <= 1)",
    )
    op.create_check_constraint(
        "ck_news_analyses_review_status",
        "news_analyses",
        "review_status IN ('not_required', 'pending', 'approved', 'rejected', 'corrected')",
    )


def downgrade() -> None:
    op.drop_constraint(
        "ck_news_analyses_review_status",
        "news_analyses",
        type_="check",
    )
    op.drop_constraint(
        "ck_news_analyses_source_reliability_range",
        "news_analyses",
        type_="check",
    )
    op.drop_constraint(
        "ck_news_analyses_sentiment_score_range",
        "news_analyses",
        type_="check",
    )
    op.drop_constraint(
        "ck_news_analyses_direction_level",
        "news_analyses",
        type_="check",
    )

    op.drop_column("news_analyses", "review_status")
    op.drop_column("news_analyses", "contradictions")
    op.drop_column("news_analyses", "key_facts")
    op.drop_column("news_analyses", "summary_en")
    op.drop_column("news_analyses", "source_reliability")
    op.drop_column("news_analyses", "direction_level")
    op.drop_column("news_analyses", "sentiment_score")

    op.execute(
        "UPDATE news_analyses SET sentiment = 'unknown' WHERE sentiment = 'mixed'"
    )
    op.drop_constraint(
        "ck_news_analyses_sentiment",
        "news_analyses",
        type_="check",
    )
    op.alter_column(
        "news_analyses",
        "sentiment",
        new_column_name="direction",
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )
    op.create_check_constraint(
        "ck_news_analyses_direction",
        "news_analyses",
        "direction IN ('positive', 'negative', 'neutral', 'unknown')",
    )
