from uuid import uuid4

import pytest
from sqlalchemy import select

from app.companies.models import Company
from app.db.session import SessionLocal
from app.news.linking import CompanyMatch
from app.news.models import ArticleCompanyLink, NewsArticle, NewsSource
from app.news.repository import NewsRepository


@pytest.mark.asyncio
async def test_candidate_company_link_upsert_is_idempotent():
    token = uuid4().hex[:8].upper()
    ticker = f"TST{token[:5]}"

    async with SessionLocal() as session:
        await session.begin()

        try:
            company = Company(
                exchange="TEST",
                ticker=ticker,
                name_en=f"Test Company {token}",
            )
            source = NewsSource(
                source_key=f"test-link-{token.lower()}",
                name="Link Test Source",
                base_url="https://example.test",
                content_policy="metadata_only",
            )
            session.add_all([company, source])
            await session.flush()

            article = NewsArticle(
                source_id=source.id,
                source_url=f"https://example.test/article/{token}",
                title_original="Test article",
                title_normalized="test article",
                language="en",
                content_rights="metadata_only",
                processing_status="pending",
            )
            session.add(article)
            await session.flush()

            match = CompanyMatch(
                company_id=company.id,
                ticker=ticker,
                matched_alias=f"Mubasher listing ticker: {ticker}",
                status="candidate",
            )
            repository = NewsRepository()

            await repository.upsert_article_company_links(
                session,
                article_id=article.id,
                matches=[match],
            )
            await repository.upsert_article_company_links(
                session,
                article_id=article.id,
                matches=[match],
            )

            links = list(
                (
                    await session.scalars(
                        select(ArticleCompanyLink).where(
                            ArticleCompanyLink.article_id == article.id,
                            ArticleCompanyLink.company_id == company.id,
                        )
                    )
                ).all()
            )

            assert len(links) == 1
            assert links[0].link_status == "candidate"
            assert links[0].link_method == "other"

        finally:
            await session.rollback()