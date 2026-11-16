from datetime import datetime, timezone
import inspect
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.news_agent.analysis_schemas import AnalysisTaskMode, StructuredAnalysisRequest
from app.agents.news_agent.analysis_tools import NewsAnalysisTools
from app.news.analysis_service import NewsAnalysisService
from app.news.groq_client import GroqAnalysisError


def analysis_row(article_id):
    return SimpleNamespace(
        id=uuid4(), article_id=article_id, company_id=None,
        analysis_version="analysis-v1", schema_version="news-analysis-v1",
        model_provider="groq", model_name="test-model", prompt_version="p1",
        taxonomy_version="t1", pipeline_version="p1", event_type="other",
        direction="unknown", relevance_score=0.5, novelty_score=0.5,
        source_reliability=None, classification_confidence={}, summary_ar=None,
        summary_en=None, key_facts=[], contradictions=[], evidence_spans=[],
        requires_human_review=True, review_status="pending", limitations=[],
        analyzed_at=datetime.now(timezone.utc),
    )


class SessionStub:
    def __init__(self):
        self.committed = False

    async def commit(self):
        self.committed = True


def test_analysis_tool_is_async_and_delegates_through_service():
    assert inspect.iscoroutinefunction(NewsAnalysisTools.structured_news_analysis)
    assert inspect.iscoroutinefunction(NewsAnalysisService.analyze_article)


def test_analysis_request_is_bounded_and_versioned():
    assert StructuredAnalysisRequest(article_ids=[uuid4()], task_mode="recheck").task_mode == AnalysisTaskMode.RECHECK
    assert StructuredAnalysisRequest(permitted_text="  permitted article text  ").permitted_text == "permitted article text"
    with pytest.raises(ValidationError):
        StructuredAnalysisRequest(article_ids=[uuid4()] * 6)
    with pytest.raises(ValidationError):
        StructuredAnalysisRequest(article_ids=[uuid4()], schema_version="other")
    with pytest.raises(ValidationError):
        StructuredAnalysisRequest()
    with pytest.raises(ValidationError):
        StructuredAnalysisRequest(article_ids=[uuid4()], permitted_text="text")
