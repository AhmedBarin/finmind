from datetime import datetime, timedelta, timezone
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, update

from app.companies.models import Company
from app.db.session import SessionLocal, engine
from app.news.models import (
    ArticleCompanyLink,
    NewsAnalysis,
    NewsArticle,
    NewsIngestionRun,
    NewsSignal,
    NewsSource,
)
from app.news.signal_service import NewsSignalService


pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module", autouse=True)
async def dispose_engine_after_module():
    await engine.dispose()
    yield
    await engine.dispose()


AS_OF = datetime(2026, 11, 13, 12, tzinfo=timezone.utc)


async def add_article_analysis(session, *, source, company, token, direction, content_hash):
    article = NewsArticle(
        source_id=source.id,
        source_url=f"https://example.test/{token}",
        title_original=f"{direction} article",
        title_normalized=f"{direction} article",
        body_original="Source evidence",
        body_cleaned="Source evidence",
        content_hash=content_hash,
        language="en",
        published_at=AS_OF - timedelta(hours=2),
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
    analysis = NewsAnalysis(
        article_id=article.id,
        company_id=company.id,
        analysis_version="analysis-v1",
        schema_version="news-analysis-v1",
        prompt_version="prompt-v1",
        taxonomy_version="taxonomy-v1",
        pipeline_version="pipeline-v1",
        event_type="earnings_results",
        direction=direction,
        relevance_score=0.9,
        novelty_score=0.8,
        classification_confidence={
            "event_type": 0.9,
            "direction": 0.9,
            "relevance": 0.9,
            "novelty": 0.8,
        },
        requires_human_review=False,
        review_status="not_required",
        evidence_spans=[],
        limitations=[],
    )
    session.add(analysis)
    await session.flush()
    return article, analysis


async def make_company_and_source(session, token: str):
    await session.execute(update(NewsSource).values(enabled=False))
    company = Company(
        exchange="TEST",
        ticker=f"SIG{token[:6].upper()}",
        name_en=f"Signal Test {token}",
    )
    source = NewsSource(
        source_key=f"signal-source-{token}",
        name="Signal Test Source",
        base_url="https://example.test",
        content_policy="full_text",
        enabled=True,
    )
    session.add_all([company, source])
    await session.flush()
    return company, source


async def add_run(session, source, *, status="success", age=timedelta(hours=1)):
    session.add(
        NewsIngestionRun(
            source_id=source.id,
            status=status,
            started_at=AS_OF - age - timedelta(minutes=5),
            finished_at=AS_OF - age,
            items_seen=1,
            items_new=1,
            items_duplicate=0,
            items_failed=0,
        )
    )
    await session.flush()


async def test_conflicts_duplicates_and_idempotent_signal_persistence():
    token = uuid4().hex[:8]
    async with SessionLocal() as session:
        await session.begin()
        try:
            company, source = await make_company_and_source(session, token)
            await add_run(session, source)
            first_article, first_analysis = await add_article_analysis(
                session,
                source=source,
                company=company,
                token=f"{token}-positive",
                direction="positive",
                content_hash="same-content",
            )
            duplicate_article, duplicate_analysis = await add_article_analysis(
                session,
                source=source,
                company=company,
                token=f"{token}-duplicate",
                direction="positive",
                content_hash="same-content",
            )
            negative_article, negative_analysis = await add_article_analysis(
                session,
                source=source,
                company=company,
                token=f"{token}-negative",
                direction="negative",
                content_hash="different-content",
            )

            service = NewsSignalService()
            first = await service.aggregate_company_signal(
                session, company_id=company.id, as_of=AS_OF
            )
            repeated = await service.aggregate_company_signal(
                session, company_id=company.id, as_of=AS_OF
            )
            rows = list(
                (
                    await session.scalars(
                        select(NewsSignal).where(NewsSignal.company_id == company.id)
                    )
                ).all()
            )

            assert first.id == repeated.id
            assert len(rows) == 1
            assert first.direction == "unknown"
            assert first.coverage_status == "available"
            assert first.article_count == 3
            assert first.eligible_article_count == 2
            assert "duplicate_content_excluded" in first.reason_codes
            assert "conflicting_directions" in first.reason_codes
            assert len(first.contributing_article_ids) == 2
            assert len(first.contributing_analysis_ids) == 2
            retained_first = str(first_article.id) in first.contributing_article_ids
            retained_duplicate = str(duplicate_article.id) in first.contributing_article_ids
            assert retained_first != retained_duplicate
            assert str(negative_article.id) in first.contributing_article_ids
        finally:
            await session.rollback()


async def test_no_news_neutral_news_and_partial_coverage_are_distinct():
    token = uuid4().hex[:8]
    async with SessionLocal() as session:
        await session.begin()
        try:
            company, source = await make_company_and_source(session, token)
            await add_run(session, source)
            service = NewsSignalService()

            no_news = await service.aggregate_company_signal(
                session, company_id=company.id, as_of=AS_OF
            )
            assert no_news.coverage_status == "no_relevant_news"
            assert no_news.direction == "unknown"

            await add_article_analysis(
                session,
                source=source,
                company=company,
                token=f"{token}-neutral",
                direction="neutral",
                content_hash="neutral-content",
            )
            neutral = await service.aggregate_company_signal(
                session, company_id=company.id, as_of=AS_OF
            )
            assert neutral.coverage_status == "available"
            assert neutral.direction == "neutral"

            second_source = NewsSource(
                source_key=f"partial-source-{token}",
                name="Partial Source",
                base_url="https://partial.example.test",
                content_policy="metadata_only",
                enabled=True,
            )
            session.add(second_source)
            await session.flush()
            await add_run(session, second_source, status="partial")
            partial = await service.aggregate_company_signal(
                session, company_id=company.id, as_of=AS_OF
            )
            assert partial.coverage_status == "partial"
            assert "source_coverage_partial" in partial.reason_codes
        finally:
            await session.rollback()


async def test_stale_source_is_reported_as_stale():
    token = uuid4().hex[:8]
    async with SessionLocal() as session:
        await session.begin()
        try:
            company, source = await make_company_and_source(session, token)
            await add_run(session, source, age=timedelta(days=3))
            signal = await NewsSignalService().aggregate_company_signal(
                session, company_id=company.id, as_of=AS_OF
            )
            assert signal.coverage_status == "stale"
            assert "source_coverage_stale" in signal.reason_codes
        finally:
            await session.rollback()
