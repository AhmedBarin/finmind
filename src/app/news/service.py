import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.news.models import NewsArticle, NewsSource
from app.news.processor import NewsProcessor
from app.news.repository import NewsRepository
from app.news.sources.registry import SourceRegistry


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IngestionSummary:
    source_key: str
    fetched: int
    saved: int
    duplicates: int
    failed: int
    run_id: UUID


class NewsService:
    def __init__(
        self,
        session_factory: async_sessionmaker[AsyncSession],
        registry: SourceRegistry,
    ) -> None:
        self.session_factory = session_factory
        self.registry = registry
        self.repository = NewsRepository()
        self.processor = NewsProcessor()

    async def ingest_source(
        self,
        source_key: str,
        *,
        since: datetime | None = None,
    ) -> IngestionSummary:
        adapter = self.registry.get(source_key)

        # Persist the source and the running record before network fetching.
        async with self.session_factory() as session:
            async with session.begin():
                source = await self.repository.get_or_create_source(
                    session,
                    source_key=adapter.source_key,
                    name=adapter.name,
                    source_type=adapter.source_type,
                    base_url=adapter.base_url,
                    content_policy=adapter.content_policy,
                )
                run = await self.repository.create_ingestion_run(
                    session,
                    source_id=source.id,
                )
                run_id = run.id
                source_id = source.id

        saved = 0
        duplicates = 0
        failed = 0
        articles = []

        try:
            articles = await adapter.fetch_articles(since=since)

            async with self.session_factory() as session:
                async with session.begin():
                    source = await session.get(NewsSource, source_id)
                    if source is None:
                        raise LookupError(
                            f"News source not found after creation: {source_key}"
                        )

                    for article in articles:
                        body_cleaned = self.processor.clean_body(
                            article.body_original
                        )
                        title_normalized = self.processor.normalize_title(
                            article.title_original
                        )
                        body_excerpt = self.processor.make_excerpt(body_cleaned)
                        content_hash = self.processor.content_hash(body_cleaned)
                        try:
                            async with session.begin_nested():
                                inserted = await self.repository.save_article(
                                    content_hash=content_hash,
                                    session=session,
                                    source=source,
                                    article=article,
                                    title_normalized=title_normalized,
                                    body_cleaned=body_cleaned,
                                    body_excerpt=body_excerpt,
                                )
                        except Exception:
                            failed += 1
                            logger.exception(
                                "Could not store article from source %s",
                                source_key,
                            )
                            continue

                        if inserted:
                            saved += 1
                        else:
                            duplicates += 1

                    status = "partial" if failed else "success"
                    await self.repository.finish_ingestion_run(
                        session,
                        run_id=run_id,
                        status=status,
                        items_seen=len(articles),
                        items_new=saved,
                        items_duplicate=duplicates,
                        items_failed=failed,
                    )

        except Exception as exc:
            async with self.session_factory() as session:
                async with session.begin():
                    await self.repository.finish_ingestion_run(
                        session,
                        run_id=run_id,
                        status="failed",
                        items_seen=len(articles),
                        items_new=saved,
                        items_duplicate=duplicates,
                        items_failed=failed,
                        error_code=type(exc).__name__,
                        error_summary=str(exc)[:1000],
                    )
            raise

        return IngestionSummary(
            source_key=source_key,
            fetched=len(articles),
            saved=saved,
            duplicates=duplicates,
            failed=failed,
            run_id=run_id,
        )

    async def list_articles(
        self,
        *,
        limit: int = 20,
        offset: int = 0,
        source_key: str | None = None,
        since: datetime | None = None,
    ) -> list[NewsArticle]:
        async with self.session_factory() as session:
            return await self.repository.list_articles(
                session,
                limit=limit,
                offset=offset,
                source_key=source_key,
                since=since,
            )