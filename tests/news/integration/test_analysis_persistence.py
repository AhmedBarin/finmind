from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select

from app.companies.models import Company
from app.db.session import SessionLocal, engine
from app.news.analysis_repository import NewsAnalysisRepository
from app.news.analysis_schemas import StructuredNewsAnalysis
from app.news.models import ArticleCompanyLink, NewsAnalysis, NewsArticle, NewsSource

pytestmark = pytest.mark.asyncio(loop_scope="module")


@pytest_asyncio.fixture(scope="module", loop_scope="module", autouse=True)
async def dispose_database_engine_after_module():
    yield
    await engine.dispose()


def make_analysis(*, summary: str, relevance: float = 0.9) -> StructuredNewsAnalysis:
    return StructuredNewsAnalysis.model_validate(
        {
            "event_type": "earnings_results",
            "direction": "positive",
            "relevance_score": relevance,
            "novelty_score": 0.8,
            "confidence": {
                "event_type": 0.95,
                "direction": 0.85,
                "relevance": 0.9,
                "novelty": 0.8,
            },
            "summary_ar": summary,
            "evidence_spans": [
                {
                    "claim": "Revenue increased.",
                    "quote": "Revenue increased by 12%.",
                    "source_field": "body_cleaned",
                    "start_char": 0,
                    "end_char": 25,
                }
            ],
            "requires_human_review": False,
            "limitations": [],
        }
    )


async def test_analysis_upsert_is_idempotent_and_preserves_versions():
    token = uuid4().hex[:8]
    ticker = f"TST{token[:5].upper()}"

    async with SessionLocal() as session:
        await session.begin()
        try:
            company = Company(
                exchange="TEST",
                ticker=ticker,
                name_en=f"Analysis Test Company {token}",
            )
            source = NewsSource(
                source_key=f"analysis-test-{token}",
                name="Analysis Test Source",
                base_url="https://example.test",
                content_policy="full_text",
            )
            session.add_all([company, source])
            await session.flush()

            article = NewsArticle(
                source_id=source.id,
                source_url=f"https://example.test/analysis/{token}",
                title_original="Quarterly results",
                title_normalized="quarterly results",
                body_original="Revenue increased by 12%.",
                body_cleaned="Revenue increased by 12%.",
                language="en",
                content_rights="full_text",
                processing_status="processed",
            )
            session.add(article)
            await session.flush()

            link = ArticleCompanyLink(
                article_id=article.id,
                company_id=company.id,
                ticker_at_analysis=ticker,
                link_method="ticker_match",
                link_status="confirmed",
                link_confidence=1.0,
                relevance_score=1.0,
            )
            session.add(link)
            await session.flush()

            repository = NewsAnalysisRepository()
            first = await repository.save_analysis(
                session,
                article_id=article.id,
                company_id=company.id,
                analysis=make_analysis(summary="الإيرادات ارتفعت."),
                analysis_version="analysis-v1",
                prompt_version="prompt-v1",
                taxonomy_version="taxonomy-v1",
                pipeline_version="pipeline-v1",
                model_provider="test-provider",
                model_name="test-model",
            )
            repeated = await repository.save_analysis(
                session,
                article_id=article.id,
                company_id=company.id,
                analysis=make_analysis(
                    summary="الإيرادات ارتفعت بنسبة 12%.",
                    relevance=0.95,
                ),
                analysis_version="analysis-v1",
                prompt_version="prompt-v1",
                taxonomy_version="taxonomy-v1",
                pipeline_version="pipeline-v1",
                model_provider="test-provider",
                model_name="test-model",
            )
            second_version = await repository.save_analysis(
                session,
                article_id=article.id,
                company_id=company.id,
                analysis=make_analysis(summary="إصدار تحليل جديد."),
                analysis_version="analysis-v2",
                prompt_version="prompt-v2",
                taxonomy_version="taxonomy-v1",
                pipeline_version="pipeline-v2",
                model_provider="test-provider",
                model_name="test-model",
            )

            rows = list(
                (
                    await session.scalars(
                        select(NewsAnalysis).where(
                            NewsAnalysis.article_id == article.id,
                            NewsAnalysis.company_id == company.id,
                        )
                    )
                ).all()
            )
            latest = await repository.get_latest_analysis(
                session,
                article_id=article.id,
                company_id=company.id,
            )

            assert first.id == repeated.id
            assert repeated.relevance_score == pytest.approx(0.95)
            assert len(rows) == 2
            assert second_version.id != first.id
            assert latest is not None
            assert latest.analysis_version == "analysis-v2"
            assert latest.direction == "positive"
            assert latest.review_status == "not_required"
            assert latest.evidence_spans[0]["quote"] == "Revenue increased by 12%."

        finally:
            await session.rollback()


async def test_company_analysis_requires_an_existing_article_company_link():
    token = uuid4().hex[:8]

    async with SessionLocal() as session:
        await session.begin()
        try:
            company = Company(
                exchange="TEST",
                ticker=f"TST{token[:5].upper()}",
                name_en=f"Unlinked Analysis Company {token}",
            )
            source = NewsSource(
                source_key=f"analysis-unlinked-{token}",
                name="Analysis Test Source",
                base_url="https://example.test",
                content_policy="full_text",
            )
            session.add_all([company, source])
            await session.flush()

            article = NewsArticle(
                source_id=source.id,
                source_url=f"https://example.test/unlinked/{token}",
                title_original="Quarterly results",
                title_normalized="quarterly results",
                body_original="Revenue increased by 12%.",
                body_cleaned="Revenue increased by 12%.",
                language="en",
                content_rights="full_text",
                processing_status="processed",
            )
            session.add(article)
            await session.flush()

            with pytest.raises(ValueError, match="requires an article-company link"):
                await NewsAnalysisRepository().save_analysis(
                    session,
                    article_id=article.id,
                    company_id=company.id,
                    analysis=make_analysis(summary="الإيرادات ارتفعت."),
                    analysis_version="analysis-v1",
                    prompt_version="prompt-v1",
                    taxonomy_version="taxonomy-v1",
                    pipeline_version="pipeline-v1",
                )
        finally:
            await session.rollback()
