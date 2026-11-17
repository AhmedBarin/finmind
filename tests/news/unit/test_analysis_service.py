from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.news.analysis_schemas import NewsDirection, StructuredNewsAnalysis
from app.news.analysis_service import NewsAnalysisService
from app.companies.models import Company


class FakeAnalysisModel:
    model_name = "fake-groq-model"

    def __init__(self, result: StructuredNewsAnalysis) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []

    async def analyze(self, **kwargs):
        self.calls.append(kwargs)
        return self.result


class FakeRepository:
    def __init__(self) -> None:
        self.values: dict[str, object] = {}

    async def save_analysis(self, session, **kwargs):
        self.values = kwargs
        return kwargs


def make_analysis() -> StructuredNewsAnalysis:
    return StructuredNewsAnalysis.model_validate(
        {
            "event_type": "earnings_results",
            "direction": "positive",
            "relevance_score": 0.9,
            "novelty_score": 0.8,
            "confidence": {
                "event_type": 0.95,
                "direction": 0.85,
                "relevance": 0.9,
                "novelty": 0.8,
            },
            "evidence_spans": [
                {
                    "claim": "Revenue increased.",
                    "quote": "Revenue increased by 12%.",
                    "source_field": "body_excerpt",
                    "start_char": 0,
                    "end_char": 25,
                }
            ],
            "requires_human_review": False,
        }
    )


def make_article(**overrides):
    values = {
        "id": uuid4(),
        "title_original": "Quarterly results",
        "body_original": None,
        "body_cleaned": None,
        "body_excerpt": "Revenue increased by 12%.",
        "content_rights": "excerpt",
        "language": "en",
        "published_at": datetime(2026, 11, 1, tzinfo=timezone.utc),
    }
    values.update(overrides)
    return type("ArticleStub", (), values)()


class SessionStub:
    def __init__(self, article) -> None:
        self.article = article

    async def get(self, model, key):
        assert key == self.article.id
        return self.article

    async def scalar(self, statement):
        raise AssertionError("No company lookup expected in this test")


@pytest.mark.asyncio
async def test_analysis_uses_only_permitted_excerpt_and_persists_version_metadata():
    article = make_article()
    model = FakeAnalysisModel(make_analysis())
    repository = FakeRepository()
    service = NewsAnalysisService(model_client=model, repository=repository)

    await service.analyze_article(SessionStub(article), article_id=article.id)

    assert model.calls[0]["article_fields"] == {
        "title_original": "Quarterly results",
        "body_excerpt": "Revenue increased by 12%.",
    }
    assert model.calls[0]["language"] == "en"
    assert model.calls[0]["company_context"] is None
    assert repository.values["model_provider"] == "groq"
    assert repository.values["model_name"] == "fake-groq-model"
    assert repository.values["prompt_version"] == "news-analysis-v1"
    assert repository.values["taxonomy_version"] == "egx-events-v1"
    assert repository.values["analysis"].direction == NewsDirection.UNKNOWN
    assert repository.values["analysis"].requires_human_review is True


@pytest.mark.asyncio
async def test_metadata_only_policy_does_not_send_any_article_body():
    article = make_article(
        body_original="Original full article",
        body_cleaned="Cleaned article",
        content_rights="metadata_only",
    )
    model = FakeAnalysisModel(make_analysis())
    service = NewsAnalysisService(model_client=model, repository=FakeRepository())

    await service.analyze_article(SessionStub(article), article_id=article.id)

    assert model.calls[0]["article_fields"] == {
        "title_original": "Quarterly results"
    }


@pytest.mark.asyncio
async def test_unconfirmed_company_link_cannot_produce_definitive_direction():
    article = make_article()
    company_id = uuid4()
    company = type(
        "CompanyStub",
        (),
        {
            "id": company_id,
            "ticker": "COMI",
            "name_en": "Commercial International Bank",
            "name_ar": "البنك التجاري الدولي",
        },
    )()
    link = type(
        "LinkStub",
        (),
        {"link_status": "candidate", "link_confidence": 0.6},
    )()

    class SessionWithCandidateLink(SessionStub):
        async def scalar(self, statement):
            return link

        async def get(self, model, key):
            if model is Company:
                assert key == company_id
                return company
            return await super().get(model, key)

    model = FakeAnalysisModel(make_analysis())
    repository = FakeRepository()
    service = NewsAnalysisService(model_client=model, repository=repository)

    await service.analyze_article(
        SessionWithCandidateLink(article),
        article_id=article.id,
        company_id=company_id,
    )

    assert model.calls[0]["company_context"]["link_status"] == "candidate"
    assert repository.values["analysis"].direction == NewsDirection.UNKNOWN
    assert repository.values["analysis"].requires_human_review is True


@pytest.mark.asyncio
async def test_article_not_found_fails_before_calling_model():
    article = make_article()

    class EmptySession:
        async def get(self, model, key):
            return None

    model = FakeAnalysisModel(make_analysis())
    service = NewsAnalysisService(model_client=model, repository=FakeRepository())

    with pytest.raises(LookupError, match="News article not found"):
        await service.analyze_article(EmptySession(), article_id=article.id)
    assert model.calls == []


def test_full_text_policy_prefers_cleaned_body_and_excerpt_policy_uses_excerpt():
    full_text_article = make_article(
        body_original="Original full article",
        body_cleaned="Cleaned article",
        content_rights="full_text",
    )
    excerpt_article = make_article(
        body_original="Do not send original",
        body_cleaned="Do not send cleaned",
        content_rights="excerpt",
    )

    assert NewsAnalysisService._permitted_article_fields(full_text_article) == {
        "title_original": "Quarterly results",
        "body_cleaned": "Cleaned article",
    }
    assert NewsAnalysisService._permitted_article_fields(excerpt_article) == {
        "title_original": "Quarterly results",
        "body_excerpt": "Revenue increased by 12%.",
    }
