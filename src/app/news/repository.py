from datetime import date, datetime, timezone
from uuid import UUID

from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.models import Company, CompanyAlias as CompanyAliasModel
from app.news.linking import CompanyAlias, CompanyMatch
from app.news.models import (
    ArticleCompanyLink,
    NewsArticle,
    NewsIngestionRun,
    NewsSource,
)
from app.news.schemas import FetchedArticle


class NewsRepository:
    @staticmethod
    def _article_identity_conditions(
        article: FetchedArticle,
        content_hash: str | None,
    ) -> list:
        conditions = [NewsArticle.source_url == article.source_url]

        if article.external_article_id:
            conditions.append(
                NewsArticle.external_article_id == article.external_article_id
            )

        if article.canonical_url:
            conditions.append(
                NewsArticle.canonical_url == article.canonical_url
            )

        if content_hash:
            conditions.append(NewsArticle.content_hash == content_hash)

        return conditions

    async def get_or_create_source(
        self,
        session: AsyncSession,
        *,
        source_key: str,
        name: str,
        source_type: str,
        base_url: str,
        content_policy: str,
    ) -> NewsSource:
        source = await session.scalar(
            select(NewsSource).where(NewsSource.source_key == source_key)
        )

        if source is None:
            source = NewsSource(
                source_key=source_key,
                name=name,
                source_type=source_type,
                base_url=base_url,
                content_policy=content_policy,
                enabled=True,
            )
            session.add(source)
        else:
            source.name = name
            source.source_type = source_type
            source.base_url = base_url
            source.content_policy = content_policy

        await session.flush()
        return source

    async def save_article(
        self,
        session: AsyncSession,
        *,
        source: NewsSource,
        article: FetchedArticle,
        title_normalized: str,
        body_cleaned: str | None,
        body_excerpt: str | None,
        content_hash: str | None,
    ) -> bool:
        identity_conditions = self._article_identity_conditions(
            article,
            content_hash,
        )

        duplicate_id = await session.scalar(
            select(NewsArticle.id)
            .where(
                NewsArticle.source_id == source.id,
                or_(*identity_conditions),
            )
            .limit(1)
        )

        if duplicate_id is not None:
            return False

        store_full_text = source.content_policy == "full_text"
        store_excerpt = source.content_policy in {"excerpt", "full_text"}

        values = {
            "source_id": source.id,
            "external_article_id": article.external_article_id,
            "source_url": article.source_url,
            "canonical_url": article.canonical_url,
            "title_original": article.title_original,
            "title_normalized": title_normalized,
            "body_original": article.body_original if store_full_text else None,
            "body_cleaned": body_cleaned if store_full_text else None,
            "body_excerpt": body_excerpt if store_excerpt else None,
            "language": article.language,
            "published_at": article.published_at,
            "content_rights": source.content_policy,
            "processing_status": "pending",
            "author": article.author,
            "updated_at_source": article.updated_at_source,
            "raw_metadata": article.raw_metadata,
            "content_hash": content_hash if store_full_text else None,
            "pipeline_version": "news-v1",
        }

        statement = (
            pg_insert(NewsArticle)
            .values(**values)
            .on_conflict_do_nothing(
                constraint="uq_article_source_external_id"
            )
            .returning(NewsArticle.id)
        )

        inserted_id = await session.scalar(statement)
        return inserted_id is not None

    async def find_article_id(
        self,
        session: AsyncSession,
        *,
        source: NewsSource,
        article: FetchedArticle,
        content_hash: str | None,
    ) -> UUID | None:
        """Find the stored article after an insert or duplicate check."""
        identity_conditions = self._article_identity_conditions(
            article,
            content_hash,
        )

        return await session.scalar(
            select(NewsArticle.id)
            .where(
                NewsArticle.source_id == source.id,
                or_(*identity_conditions),
            )
            .limit(1)
        )

    async def list_verified_company_aliases(
        self,
        session: AsyncSession,
        *,
        as_of: date | None = None,
    ) -> list[CompanyAlias]:
        today = as_of or datetime.now(timezone.utc).date()

        statement = (
            select(
                CompanyAliasModel.company_id,
                Company.ticker,
                CompanyAliasModel.alias_text,
            )
            .join(Company, Company.id == CompanyAliasModel.company_id)
            .where(
                Company.is_active.is_(True),
                CompanyAliasModel.verification_status == "verified",
                or_(
                    CompanyAliasModel.valid_from.is_(None),
                    CompanyAliasModel.valid_from <= today,
                ),
                or_(
                    CompanyAliasModel.valid_to.is_(None),
                    CompanyAliasModel.valid_to >= today,
                ),
            )
            .order_by(
                CompanyAliasModel.alias_normalized,
                Company.ticker,
            )
        )

        rows = (await session.execute(statement)).all()

        return [
            CompanyAlias(
                company_id=company_id,
                ticker=ticker,
                alias_text=alias_text,
            )
            for company_id, ticker, alias_text in rows
        ]

    async def upsert_article_company_links(
        self,
        session: AsyncSession,
        *,
        article_id: UUID,
        matches: list[CompanyMatch],
    ) -> None:
        for match in matches:
            is_ticker_match = match.matched_alias.casefold() == match.ticker.casefold()
            if match.status == "candidate":
                link_method = "other"
            elif match.matched_alias.casefold() == match.ticker.casefold():
                link_method = "ticker_match"
            else:
                link_method = "exact_alias"

            is_confirmed = match.status == "confirmed"

            values = {
                "article_id": article_id,
                "company_id": match.company_id,
                "ticker_at_analysis": match.ticker,
                "relevance_score": 1.0 if is_confirmed else None,
                "link_confidence": 1.0 if is_confirmed else None,
                "link_method": link_method,
                "link_status": match.status,
                "evidence_spans": [
                    {"matched_alias": match.matched_alias}
                ],
            }

            statement = (
                pg_insert(ArticleCompanyLink)
                .values(**values)
                .on_conflict_do_update(
                    constraint="uq_article_company_links_article_company",
                    set_={
                        "ticker_at_analysis": values["ticker_at_analysis"],
                        "relevance_score": values["relevance_score"],
                        "link_confidence": values["link_confidence"],
                        "link_method": values["link_method"],
                        "link_status": values["link_status"],
                        "evidence_spans": values["evidence_spans"],
                        "updated_at": func.now(),
                    },
                )
            )
            await session.execute(statement)

    async def list_articles(
        self,
        session: AsyncSession,
        *,
        limit: int = 20,
        offset: int = 0,
        source_key: str | None = None,
        since: datetime | None = None,
    ) -> list[NewsArticle]:
        statement = select(NewsArticle)

        if source_key:
            statement = statement.join(
                NewsSource,
                NewsArticle.source_id == NewsSource.id,
            ).where(NewsSource.source_key == source_key)

        if since:
            statement = statement.where(NewsArticle.published_at >= since)

        statement = (
            statement
            .order_by(
                NewsArticle.published_at.desc().nullslast(),
                NewsArticle.retrieved_at.desc(),
            )
            .limit(limit)
            .offset(offset)
        )

        result = await session.scalars(statement)
        return list(result.all())

    async def create_ingestion_run(
        self,
        session: AsyncSession,
        *,
        source_id: UUID,
    ) -> NewsIngestionRun:
        run = NewsIngestionRun(source_id=source_id)
        session.add(run)
        await session.flush()
        return run

    async def finish_ingestion_run(
        self,
        session: AsyncSession,
        *,
        run_id: UUID,
        status: str,
        items_seen: int,
        items_new: int,
        items_duplicate: int,
        items_failed: int,
        error_code: str | None = None,
        error_summary: str | None = None,
    ) -> NewsIngestionRun:
        run = await session.get(NewsIngestionRun, run_id)
        if run is None:
            raise LookupError(f"Ingestion run not found: {run_id}")

        run.status = status
        run.finished_at = datetime.now(timezone.utc)
        run.items_seen = items_seen
        run.items_new = items_new
        run.items_duplicate = items_duplicate
        run.items_failed = items_failed
        run.error_code = error_code
        run.error_summary = error_summary

        await session.flush()
        return run