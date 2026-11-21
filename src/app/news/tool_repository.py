"""Read-only database queries used by News Agent tools."""

from dataclasses import dataclass
from datetime import datetime
import re
from uuid import UUID

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.models import Company, CompanyAlias
from app.news.linking import normalize_company_text
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
        # Treat an exact ticker/company alias query as a company request. This
        # prevents a query such as ``COMI`` from returning arbitrary articles
        # whose full body happens to contain the same text.
        company_scope = company_id
        if company_scope is None and not tickers and query:
            normalized_query = self._normalize_query(query)
            company_scope = await session.scalar(
                select(Company.id)
                .join(CompanyAlias, CompanyAlias.company_id == Company.id)
                .where(
                    Company.is_active.is_(True),
                    CompanyAlias.alias_normalized == normalized_query,
                )
            )

        latest_analysis = (
            select(NewsAnalysis.id)
            .where(NewsAnalysis.article_id == NewsArticle.id)
            .order_by(NewsAnalysis.analyzed_at.desc(), NewsAnalysis.created_at.desc())
            .limit(1)
            .correlate(NewsArticle)
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
        if company_scope is not None:
            statement = statement.where(ArticleCompanyLink.company_id == company_scope, ArticleCompanyLink.link_status == "confirmed")
        elif tickers:
            statement = statement.where(Company.ticker.in_([ticker.upper() for ticker in tickers]), ArticleCompanyLink.link_status == "confirmed")
        # Exact company aliases are already enforced by the confirmed link;
        # applying a second substring filter would incorrectly exclude an
        # article that says ``CIB`` when the caller searched for ``COMI``.
        if query and company_scope is None:
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
        # First choose distinct article IDs. A single article can have many
        # company links, so limiting the joined rows directly can return fewer
        # than ``limit`` distinct articles.
        article_ids_statement = (
            statement.with_only_columns(
                NewsArticle.id,
                NewsArticle.published_at,
            )
            .group_by(NewsArticle.id, NewsArticle.published_at)
            .order_by(NewsArticle.published_at.desc())
            .limit(min(limit * 5, 100))
        )
        article_ids = list((await session.scalars(article_ids_statement)).all())
        if not article_ids:
            return []

        statement = (
            statement.where(NewsArticle.id.in_(article_ids))
            .order_by(NewsArticle.published_at.desc())
        )
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
        rows = list(grouped.values())
        if query and company_scope is None:
            rows.sort(key=lambda row: self._relevance_score(row, query), reverse=True)
        return rows[:limit]

    @staticmethod
    def _normalize_query(value: str) -> str:
        return normalize_company_text(value)

    @classmethod
    def _relevance_score(cls, row: ToolArticleRow, query: str) -> float:
        """Rank text-search results without treating relevance as impact."""
        normalized_query = cls._normalize_query(query)
        title = cls._normalize_query(row.article.title_original)
        excerpt = cls._normalize_query(row.article.body_excerpt or "")
        body = cls._normalize_query(row.article.body_cleaned or "")
        score = 0.0
        if normalized_query in title:
            score += 1.0
        elif normalized_query in excerpt:
            score += 0.6
        elif normalized_query in body:
            score += 0.3
        query_terms = set(re.findall(r"\w+", normalized_query))
        if query_terms:
            title_terms = set(re.findall(r"\w+", title))
            score += 0.4 * len(query_terms & title_terms) / len(query_terms)
        return score
