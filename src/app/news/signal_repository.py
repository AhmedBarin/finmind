"""Persistence operations for deterministic company news signals."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.news.models import ArticleCompanyLink, NewsAnalysis, NewsArticle, NewsIngestionRun, NewsSignal, NewsSource


@dataclass(frozen=True)
class SignalCandidate:
    analysis: NewsAnalysis
    article: NewsArticle
    link: ArticleCompanyLink


class NewsSignalRepository:
    async def list_company_candidates(self, session: AsyncSession, *, company_id: UUID, window_start: datetime, window_end: datetime) -> list[SignalCandidate]:
        statement = (
            select(NewsAnalysis, NewsArticle, ArticleCompanyLink)
            .join(NewsArticle, NewsArticle.id == NewsAnalysis.article_id)
            .join(ArticleCompanyLink, (ArticleCompanyLink.article_id == NewsAnalysis.article_id) & (ArticleCompanyLink.company_id == NewsAnalysis.company_id))
            .where(NewsAnalysis.company_id == company_id, NewsArticle.published_at.is_not(None), NewsArticle.published_at >= window_start, NewsArticle.published_at <= window_end)
            .order_by(NewsAnalysis.analyzed_at.desc(), NewsAnalysis.created_at.desc())
        )
        return [SignalCandidate(analysis=a, article=n, link=l) for a, n, l in (await session.execute(statement)).all()]

    async def list_enabled_sources(self, session: AsyncSession) -> list[NewsSource]:
        return list((await session.scalars(select(NewsSource).where(NewsSource.enabled.is_(True)))).all())

    async def list_completed_ingestion_runs(self, session: AsyncSession) -> list[NewsIngestionRun]:
        return list((await session.scalars(select(NewsIngestionRun).where(NewsIngestionRun.finished_at.is_not(None)).order_by(NewsIngestionRun.source_id, NewsIngestionRun.finished_at.desc()))).all())

    async def save_signal(self, session: AsyncSession, *, values: dict) -> NewsSignal:
        statement = pg_insert(NewsSignal).values(**values).on_conflict_do_update(
            constraint="uq_news_signals_company_config_input", set_=values
        ).returning(NewsSignal)
        signal = await session.scalar(statement.execution_options(populate_existing=True))
        if signal is None:
            raise RuntimeError("News signal upsert did not return a record")
        return signal
