import logging
from dataclasses import dataclass
from datetime import datetime
from uuid import UUID

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.news.linking import match_companies
from app.news.models import NewsArticle, NewsSource
from app.news.processor import NewsProcessor
from app.news.repository import NewsRepository
from app.news.sources.registry import SourceRegistry
from app.news.tool_repository import NewsToolRepository, ToolArticleRow
from app.agents.news_agent.schemas import (
    CompanyNewsRequest,
    NewsToolArticle,
    NewsToolData,
    RecentNewsRequest,
    SearchNewsRequest,
)


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
        self.tool_repository = NewsToolRepository()

    async def ingest_source(
        self,
        source_key: str,
        *,
        since: datetime | None = None,
    ) -> IngestionSummary:
        adapter = self.registry.get(source_key)

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

                    aliases = await self.repository.list_verified_company_aliases(
                        session
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
                                    session,
                                    source=source,
                                    article=article,
                                    title_normalized=title_normalized,
                                    body_cleaned=body_cleaned,
                                    body_excerpt=body_excerpt,
                                    content_hash=content_hash,
                                )

                                article_id = await self.repository.find_article_id(
                                    session,
                                    source=source,
                                    article=article,
                                    content_hash=content_hash,
                                )
                                if article_id is None:
                                    raise LookupError(
                                        "Could not find the stored article after save."
                                    )

                                text_parts = [article.title_original]
                                if source.content_policy == "full_text" and body_cleaned:
                                    text_parts.append(body_cleaned)
                                elif (
                                    source.content_policy == "excerpt"
                                    and body_excerpt
                                ):
                                    text_parts.append(body_excerpt)

                                matches = match_companies(
                                        "\n".join(text_parts),
                                        aliases,
                                        context_tickers=article.raw_metadata.get(
                                            "mubasher_listing_tickers",
                                            [],
                                        ),
                                    )

                                await self.repository.upsert_article_company_links(
                                    session,
                                    article_id=article_id,
                                    matches=matches,
                                )

                        except Exception:
                            failed += 1
                            logger.exception(
                                "Could not store or link article from source %s",
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

    async def search_news(self, session: AsyncSession, request: SearchNewsRequest) -> NewsToolData:
        rows = await self.tool_repository.list_articles(
            session, query=request.query, company_id=request.company_id,
            tickers=request.tickers,
            start_at=request.start_at, end_at=request.end_at,
            event_types=request.event_types, directions=request.directions,
            source_types=request.source_types, language=request.language,
            limit=request.limit,
        )
        return self._tool_data(rows)

    async def get_recent_news(self, session: AsyncSession, request: RecentNewsRequest) -> NewsToolData:
        rows = await self.tool_repository.list_articles(
            session, company_id=request.company_id, tickers=request.tickers, start_at=request.start_at,
            end_at=request.end_at, event_types=request.event_types,
            directions=request.directions, source_types=request.source_types,
            language=request.language, limit=request.limit,
        )
        return self._tool_data(rows)

    async def get_company_news(self, session: AsyncSession, request: CompanyNewsRequest) -> NewsToolData:
        company = await self.tool_repository.resolve_company(
            session, ticker=request.ticker, company_id=request.company_id
        )
        if company is None:
            raise LookupError("Company not found")
        rows = await self.tool_repository.list_articles(
            session, company_id=company.id, start_at=request.start_at,
            end_at=request.end_at, event_types=request.event_types,
            directions=request.directions, source_types=request.source_types,
            language=request.language, limit=request.limit,
        )
        return self._tool_data(rows)

    @staticmethod
    def _tool_data(rows: list[ToolArticleRow]) -> NewsToolData:
        articles = []
        for row in rows:
            article = row.article
            # Full text is deliberately never returned by these bounded tools.
            snippet = article.title_original
            if article.content_rights in {"excerpt", "full_text", "full_text_permitted"}:
                snippet = article.body_excerpt or article.title_original
            analysis = row.analysis
            articles.append(NewsToolArticle(
                article_id=article.id,
                title=article.title_original,
                published_at=article.published_at,
                source_name=row.source.name,
                source_type=row.source.source_type,
                source_url=article.source_url,
                language=article.language,
                content_rights=article.content_rights,
                snippet=snippet,
                relevance_score=(analysis.relevance_score if analysis else None),
                ticker_links=list(row.company_tickers),
                link_confidence=[link.link_confidence for link in row.links if link.link_confidence is not None],
                direction=(analysis.direction if analysis else None),
                event_type=(analysis.event_type if analysis else None),
                analysis_status=(analysis.review_status if analysis else "not_analyzed"),
                evidence=(analysis.evidence_spans if analysis else []),
            ))
        return NewsToolData(articles=articles, coverage_status="available" if articles else "no_relevant_news")
