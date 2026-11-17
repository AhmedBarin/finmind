from datetime import datetime, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import delete

from app.companies.models import Company
from app.db.session import SessionLocal, engine
from app.news.models import ArticleCompanyLink, NewsArticle, NewsSource
from app.news.tool_repository import NewsToolRepository


pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module", autouse=True)
async def dispose_engine_after_module():
    await engine.dispose()
    yield
    await engine.dispose()


async def test_list_articles_executes_against_postgres_without_correlation_error():
    token = uuid4().hex[:12]
    company = Company(
        exchange="TEST",
        ticker=f"TOOL{token[:6].upper()}",
        name_en="News Tool Repository Test",
        is_active=True,
    )
    source = NewsSource(
        source_key=f"tool-repository-{token}",
        name="Tool Repository Test Source",
        source_type="test",
        base_url="https://example.test",
        content_policy="full_text",
        enabled=True,
    )

    async with SessionLocal() as session:
        async with session.begin():
            session.add_all([company, source])
            await session.flush()
            article = NewsArticle(
                source_id=source.id,
                source_url=f"https://example.test/article/{token}",
                title_original="Repository integration test article",
                title_normalized="repository integration test article",
                body_cleaned="Repository integration test evidence",
                body_original="Repository integration test evidence",
                language="en",
                published_at=datetime.now(timezone.utc),
                content_rights="full_text",
                processing_status="processed",
            )
            session.add(article)
            await session.flush()
            session.add(
                ArticleCompanyLink(
                    article_id=article.id,
                    company_id=company.id,
                    ticker_at_analysis=company.ticker,
                    link_method="ticker_match",
                    link_status="confirmed",
                    link_confidence=1.0,
                    relevance_score=1.0,
                )
            )
            await session.flush()

            rows = await NewsToolRepository().list_articles(
                session,
                company_id=company.id,
                limit=1,
            )
            assert len(rows) == 1
            assert rows[0].article.id == article.id
            assert rows[0].company_tickers == (company.ticker,)

            await session.execute(
                delete(ArticleCompanyLink).where(ArticleCompanyLink.article_id == article.id)
            )
            await session.delete(article)
            await session.delete(company)
            await session.delete(source)
