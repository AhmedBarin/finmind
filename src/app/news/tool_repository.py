"""Read-only database queries used by News Agent tools."""

from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.models import Company
from app.news.models import ArticleCompanyLink, NewsAnalysis, NewsArticle, NewsSource


@dataclass(frozen=True)
class ToolArticleRow:
    article: NewsArticle
    source: NewsSource
    links: tuple[ArticleCompanyLink, ...]
    company_tickers: tuple[str, ...]
    analysis: NewsAnalysis | None


class NewsToolRepository:
    async def resolve_company(self, session: AsyncSession, *, ticker: str | None, company_id: UUID | None) -> Company | None:
        if company_id is not None:
            return await session.scalar(select(Company).where(Company.id == company_id, Company.is_active.is_(True)))
        if ticker:
            return await session.scalar(select(Company).where(Company.ticker == ticker.upper(), Company.is_active.is_(True)))
        return None

    async def list_articles(
        self, session: AsyncSession, *, query: str | None = None,
        tickers: list[str] | None = None,
        company_id: UUID | None = None, start_at: datetime | None = None,
        end_at: datetime | None = None, event_types: list[str] | None = None,
        directions: list[str] | None = None, source_types: list[str] | None = None,
        language: str | None = None, limit: int = 20,
    ) -> list[ToolArticleRow]:
        latest_analysis = (
            select(NewsAnalysis.id)
            .where(NewsAnalysis.article_id == NewsArticle.id)
            .order_by(NewsAnalysis.analyzed_at.desc(), NewsAnalysis.created_at.desc())
            .limit(1)
            .scalar_subquery()
        )
        statement = (
            select(NewsArticle, NewsSource, ArticleCompanyLink, Company, NewsAnalysis)
            .join(NewsSource, NewsSource.id == NewsArticle.source_id)
            .outerjoin(ArticleCompanyLink, ArticleCompanyLink.article_id == NewsArticle.id)
            .outerjoin(Company, Company.id == ArticleCompanyLink.company_id)
            .outerjoin(NewsAnalysis, NewsAnalysis.id == latest_analysis)
            .where(NewsArticle.published_at.is_not(None))
        )
        if company_id is not None:
            statement = statement.where(ArticleCompanyLink.company_id == company_id, ArticleCompanyLink.link_status == "confirmed")
        elif tickers:
            statement = statement.where(Company.ticker.in_([ticker.upper() for ticker in tickers]), ArticleCompanyLink.link_status == "confirmed")
        if query:
            pattern = f"%{query}%"
            statement = statement.where(or_(NewsArticle.title_original.ilike(pattern), NewsArticle.body_excerpt.ilike(pattern), NewsArticle.body_cleaned.ilike(pattern)))
        if start_at is not None:
            statement = statement.where(NewsArticle.published_at >= start_at)
        if end_at is not None:
            statement = statement.where(NewsArticle.published_at <= end_at)
        if event_types:
            statement = statement.where(NewsAnalysis.event_type.in_(event_types))
        if directions:
            statement = statement.where(NewsAnalysis.direction.in_(directions))
        if source_types:
            statement = statement.where(NewsSource.source_type.in_(source_types))
        if language and language != "mixed":
            statement = statement.where(NewsArticle.language == language)
        statement = statement.order_by(NewsArticle.published_at.desc()).limit(limit * 5)
        rows = (await session.execute(statement)).all()
        grouped: dict[UUID, ToolArticleRow] = {}
        for article, source, link, company, analysis in rows:
            current = grouped.get(article.id)
            links = list(current.links) if current else []
            tickers = list(current.company_tickers) if current else []
            if link and link.link_status == "confirmed" and link.id not in {item.id for item in links}:
                links.append(link)
                if company and company.ticker not in tickers:
                    tickers.append(company.ticker)
            grouped[article.id] = ToolArticleRow(article, source, tuple(links), tuple(tickers), analysis or (current.analysis if current else None))
            if len(grouped) >= limit:
                break
        return list(grouped.values())
