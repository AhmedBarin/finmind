from __future__ import annotations

from datetime import date

import pytest

from app.explanation.adapters import adapt_follow_up, adapt_recommendation
from app.explanation.evidence import NewsEvidenceRetriever
from app.explanation.generator import ExplanationDraft, ExplanationGenerator
from app.explanation.graph import ExplanationGraph
from app.explanation.schemas import (
    DataAvailability,
    EvidenceItem,
    EvidenceResult,
    ExplanationLanguage,
    FollowUpRequest,
    RecommendationExplanationRequest,
)
from app.investor.checkpointer import create_memory_checkpointer
from app.recommendation.schemas import (
    ConfidenceLevel,
    RecommendationDataQuality,
    RecommendationDecision,
    RecommendationResult,
)


class FakeLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.calls = []

    async def generate_structured(self, **kwargs):
        self.calls.append(kwargs)
        output = self.outputs.pop(0)
        return output


class FakeEvidenceRetriever:
    def __init__(self, result=None):
        self.result = result or EvidenceResult(status=DataAvailability.NOT_FOUND)
        self.queries = []

    async def retrieve(self, query):
        self.queries.append(query)
        return self.result


def _draft(*, decision=None, citations=None, summary="شرح مسجل"):
    return ExplanationDraft(
        summary=summary,
        explanation="التفسير يستند إلى البيانات المقدمة.",
        facts=[],
        citation_ids=citations or [],
        limitations=[],
        disclaimer="هذا الشرح لأغراض المعلومات ودعم القرار فقط، وليس نصيحة مالية أو ضماناً للأرباح.",
        decision=decision,
    )


def _recommendation_request():
    recommendation = RecommendationResult(
        ticker="COMI",
        trading_date=date(2026, 11, 24),
        config_version="recommendation-v1",
        decision=RecommendationDecision.WATCH,
        confidence=ConfidenceLevel.MEDIUM,
        indicators={"rsi14": 54.2},
        data_quality=RecommendationDataQuality(
            price_status="valid", last_price_date=date(2026, 11, 24)
        ),
    )
    return RecommendationExplanationRequest(recommendation=recommendation)


def _graph(llm, retriever=None):
    return ExplanationGraph(
        generator=ExplanationGenerator(llm),
        retriever=NewsEvidenceRetriever(retriever or FakeEvidenceRetriever()),
        checkpointer=create_memory_checkpointer(),
    )


@pytest.mark.asyncio
async def test_graph_retries_changed_decision_and_returns_only_retrieved_citations():
    source = EvidenceItem(
        evidence_id="article-1",
        article_id="00000000-0000-0000-0000-000000000333",
        title="Company filing",
        ticker="COMI",
    )
    retriever = FakeEvidenceRetriever(
        EvidenceResult(status=DataAvailability.AVAILABLE, items=[source])
    )
    llm = FakeLLM(
        [
            _draft(decision=RecommendationDecision.BUY, citations=["fabricated"]),
            _draft(decision=RecommendationDecision.WATCH, citations=["article-1"]),
        ]
    )
    graph = _graph(llm, retriever)
    request = _recommendation_request()
    response = await graph.ainvoke(
        adapted=adapt_recommendation(request),
        user_id="user-1",
        thread_id="decision-thread",
        expected_decision=RecommendationDecision.WATCH,
    )

    assert response.decision is RecommendationDecision.WATCH
    assert [item.evidence_id for item in response.citations] == ["article-1"]
    assert len(llm.calls) == 2
    assert "failed validation" in llm.calls[1]["system_prompt"]


@pytest.mark.asyncio
async def test_graph_uses_safe_fallback_after_second_invalid_citation():
    llm = FakeLLM(
        [
            _draft(decision=RecommendationDecision.WATCH, citations=["invented-id"]),
            _draft(decision=RecommendationDecision.WATCH, citations=["invented-id"]),
        ]
    )
    graph = _graph(llm)
    response = await graph.ainvoke(
        adapted=adapt_recommendation(_recommendation_request()),
        user_id="user-1",
        thread_id="fallback-thread",
        expected_decision=RecommendationDecision.WATCH,
    )

    assert response.decision is RecommendationDecision.WATCH
    assert response.citations == []
    assert "تعذر إنشاء شرح موثوق" in response.explanation
    assert len(llm.calls) == 2


@pytest.mark.asyncio
async def test_follow_up_memory_is_thread_and_user_scoped():
    llm = FakeLLM(
        [
            _draft(summary="First explanation."),
            _draft(summary="Second explanation."),
        ]
    )
    graph = _graph(llm)
    first = adapt_follow_up(
        FollowUpRequest(
            question="What was the earlier explanation?",
            subject_type="stock_qa",
            prior_context={"ticker": "COMI"},
            thread_id="shared-thread",
                language=ExplanationLanguage.ARABIC,
        )
    )
    second = adapt_follow_up(
        FollowUpRequest(
            question="Can you clarify it?",
            subject_type="stock_qa",
            prior_context={"ticker": "COMI"},
            thread_id="shared-thread",
                language=ExplanationLanguage.ARABIC,
        )
    )

    await graph.ainvoke(adapted=first, user_id="user-a", thread_id="shared-thread")
    await graph.ainvoke(adapted=second, user_id="user-a", thread_id="shared-thread")
    await graph.ainvoke(adapted=second, user_id="user-b", thread_id="shared-thread")

    assert "First explanation." in llm.calls[1]["user_prompt"]
    assert "First explanation." not in llm.calls[2]["user_prompt"]
