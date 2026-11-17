from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

from fastapi.testclient import TestClient

from app.core.dependencies import get_db_session, get_news_analysis_service
from app.main import app
from app.news.groq_client import GroqAnalysisError


class SessionStub:
    def __init__(self) -> None:
        self.committed = False

    async def commit(self) -> None:
        self.committed = True


class AnalysisServiceStub:
    def __init__(self, result=None, error=None) -> None:
        self.result = result
        self.error = error
        self.call = None

    async def analyze_article(self, session, *, article_id, company_id=None):
        self.call = (session, article_id, company_id)
        if self.error:
            raise self.error
        return self.result


def analysis_row(article_id, company_id=None):
    return SimpleNamespace(
        id=uuid4(),
        article_id=article_id,
        company_id=company_id,
        analysis_version="analysis-v1",
        schema_version="news-analysis-v1",
        model_provider="groq",
        model_name="test-model",
        prompt_version="news-analysis-v1",
        taxonomy_version="egx-events-v1",
        pipeline_version="groq-analysis-v1",
        event_type="earnings_results",
        direction="unknown",
        relevance_score=0.8,
        novelty_score=0.5,
        source_reliability=None,
        classification_confidence={
            "event_type": 0.9,
            "direction": 0.5,
            "relevance": 0.8,
            "novelty": 0.5,
        },
        summary_ar=None,
        summary_en=None,
        key_facts=[],
        contradictions=[],
        evidence_spans=[],
        requires_human_review=True,
        review_status="pending",
        limitations=["No company was linked."],
        analyzed_at=datetime.now(timezone.utc),
    )


def test_analyze_article_endpoint_returns_persisted_analysis_and_commits():
    article_id = uuid4()
    company_id = uuid4()
    session = SessionStub()
    service = AnalysisServiceStub(analysis_row(article_id, company_id))

    async def override_session():
        yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_news_analysis_service] = lambda: service
    try:
        response = TestClient(app).post(
            f"/news/articles/{article_id}/analysis?company_id={company_id}"
        )
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 200
    assert response.json()["direction"] == "unknown"
    assert response.json()["model_name"] == "test-model"
    assert service.call == (session, article_id, company_id)
    assert session.committed is True


def test_analyze_article_endpoint_maps_groq_failure_to_bad_gateway():
    article_id = uuid4()
    session = SessionStub()
    service = AnalysisServiceStub(error=GroqAnalysisError("Groq unavailable"))

    async def override_session():
        yield session

    app.dependency_overrides[get_db_session] = override_session
    app.dependency_overrides[get_news_analysis_service] = lambda: service
    try:
        response = TestClient(app).post(f"/news/articles/{article_id}/analysis")
    finally:
        app.dependency_overrides.clear()

    assert response.status_code == 502
    assert response.json() == {"detail": "Groq unavailable"}
    assert session.committed is False
