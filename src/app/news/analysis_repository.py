"""Persistence operations for versioned structured news analyses."""

from datetime import datetime, timezone
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.news.analysis_schemas import (
    StructuredNewsAnalysis,
    validate_evidence_against_article,
)
from app.news.models import ArticleCompanyLink, NewsAnalysis, NewsArticle


class NewsAnalysisRepository:
    async def save_analysis(
        self,
        session: AsyncSession,
        *,
        article_id: UUID,
        company_id: UUID | None,
        analysis: StructuredNewsAnalysis,
        analysis_version: str,
        prompt_version: str,
        taxonomy_version: str,
        pipeline_version: str,
        model_provider: str | None = None,
        model_name: str | None = None,
    ) -> NewsAnalysis:
        """Validate evidence provenance and idempotently save one analysis version."""

        article = await session.get(NewsArticle, article_id)
        if article is None:
            raise LookupError(f"News article not found: {article_id}")

        validate_evidence_against_article(
            analysis,
            title_original=article.title_original,
            body_original=article.body_original,
            body_cleaned=article.body_cleaned,
            body_excerpt=article.body_excerpt,
        )

        if company_id is not None:
            link_id = await session.scalar(
                select(ArticleCompanyLink.id).where(
                    ArticleCompanyLink.article_id == article_id,
                    ArticleCompanyLink.company_id == company_id,
                )
            )
            if link_id is None:
                raise ValueError(
                    "A company-specific analysis requires an article-company link"
                )

        values = {
            "article_id": article_id,
            "company_id": company_id,
            "analysis_version": analysis_version,
            "schema_version": analysis.schema_version,
            "model_provider": model_provider,
            "model_name": model_name,
            "prompt_version": prompt_version,
            "taxonomy_version": taxonomy_version,
            "pipeline_version": pipeline_version,
            "event_type": analysis.event_type.value,
            "direction": analysis.direction.value,
            "relevance_score": analysis.relevance_score,
            "novelty_score": analysis.novelty_score,
            "classification_confidence": analysis.confidence.model_dump(mode="json"),
            "summary_ar": analysis.summary_ar,
            "evidence_spans": [
                span.model_dump(mode="json") for span in analysis.evidence_spans
            ],
            "requires_human_review": analysis.requires_human_review,
            "limitations": analysis.limitations,
            "analyzed_at": datetime.now(timezone.utc),
        }

        statement = pg_insert(NewsAnalysis).values(**values)
        if company_id is None:
            statement = statement.on_conflict_do_update(
                index_elements=[
                    NewsAnalysis.article_id,
                    NewsAnalysis.analysis_version,
                ],
                index_where=NewsAnalysis.company_id.is_(None),
                set_={**values, "updated_at": func.now()},
            )
        else:
            statement = statement.on_conflict_do_update(
                index_elements=[
                    NewsAnalysis.article_id,
                    NewsAnalysis.company_id,
                    NewsAnalysis.analysis_version,
                ],
                index_where=NewsAnalysis.company_id.is_not(None),
                set_={**values, "updated_at": func.now()},
            )

        saved = await session.scalar(
            statement.returning(NewsAnalysis).execution_options(
                populate_existing=True
            )
        )
        if saved is None:
            raise RuntimeError("News analysis upsert did not return a record")
        return saved

    async def get_latest_analysis(
        self,
        session: AsyncSession,
        *,
        article_id: UUID,
        company_id: UUID | None = None,
    ) -> NewsAnalysis | None:
        """Return the latest analysis for an article or a specific company link."""

        statement = select(NewsAnalysis).where(
            NewsAnalysis.article_id == article_id
        )
        if company_id is None:
            statement = statement.where(NewsAnalysis.company_id.is_(None))
        else:
            statement = statement.where(NewsAnalysis.company_id == company_id)

        statement = statement.order_by(
            NewsAnalysis.analyzed_at.desc(),
            NewsAnalysis.created_at.desc(),
        )
        return await session.scalar(
            statement.limit(1).execution_options(populate_existing=True)
        )
