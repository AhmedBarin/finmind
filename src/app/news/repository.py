from sqlalchemy import or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession
from datetime import datetime
from app.news.models import NewsArticle, NewsSource
from app.news.schemas import FetchedArticle
from datetime import datetime, timezone
from app.news.models import NewsArticle, NewsIngestionRun, NewsSource

class NewsRepository:
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
        identity_conditions = [
            NewsArticle.source_url == article.source_url,
        ]

        if article.external_article_id:
            identity_conditions.append(
                NewsArticle.external_article_id == article.external_article_id
            )

        if article.canonical_url:
            identity_conditions.append(
                NewsArticle.canonical_url == article.canonical_url
            )

        if content_hash:
            identity_conditions.append(
                NewsArticle.content_hash == content_hash
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

        policy = source.content_policy
        store_full_text = policy == "full_text"
        store_excerpt = policy in {"excerpt", "full_text"}

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
            "content_rights": policy,
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
            statement = statement.where(
                NewsArticle.published_at >= since
            )

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
        source_id: int,
    ) -> NewsIngestionRun:
        run = NewsIngestionRun(source_id=source_id)
        session.add(run)
        await session.flush()
        return run

    async def finish_ingestion_run(
        self,
        session: AsyncSession,
        *,
        run_id: int,
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