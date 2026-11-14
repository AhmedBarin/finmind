"""align news direction contract

Revision ID: d53a17e8bc42
Revises: f17c9305ae62
Create Date: 2026-11-13
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d53a17e8bc42"
down_revision: Union[str, Sequence[str], None] = "f17c9305ae62"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_constraint(
        "ck_news_analyses_sentiment",
        "news_analyses",
        type_="check",
    )
    op.drop_constraint(
        "ck_news_analyses_direction_level",
        "news_analyses",
        type_="check",
    )
    op.drop_constraint(
        "ck_news_analyses_sentiment_score_range",
        "news_analyses",
        type_="check",
    )

    op.execute(
        "UPDATE news_analyses SET sentiment = 'unknown', "
        "requires_human_review = true, review_status = 'pending' "
        "WHERE sentiment = 'mixed'"
    )
    op.alter_column(
        "news_analyses",
        "sentiment",
        new_column_name="direction",
        existing_type=sa.String(length=20),
        existing_nullable=False,
    )
    op.drop_column("news_analyses", "direction_level")
    op.drop_column("news_analyses", "sentiment_score")
    op.create_check_constraint(
        "ck_news_analyses_direction",
        "news_analyses",
        "direction IN ('positive', 'negative', 'neutral', 'unknown')",
    )


def downgrade() -> None:
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
    op.create_check_constraint(
        "ck_news_analyses_sentiment",
        "news_analyses",
        "sentiment IN ('positive', 'neutral', 'negative', 'mixed', 'unknown')",
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
