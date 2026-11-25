from datetime import UTC, date, datetime
from uuid import uuid4

import pytest

from app.agents.news_agent.retrieval_schemas import (
    RetrievalData,
    RetrievalToolResponse,
    SimilarNewsItem,
)
from app.agents.news_agent.schemas import ToolStatus
from app.explanation.evidence import (
    NewsEvidenceRetriever,
    NewsToolsEvidenceBackend,
    build_evidence_query,
)
from app.explanation.schemas import DataAvailability, EvidenceItem, EvidenceResult


class Backend:
    async def retrieve(self, query):
        return EvidenceResult(
            status=DataAvailability.AVAILABLE,
            items=[
                EvidenceItem(evidence_id="1", title="COMI", ticker="COMI"),
                EvidenceItem(evidence_id="1", title="duplicate", ticker="COMI"),
                EvidenceItem(evidence_id="2", title="SWDY", ticker="SWDY"),
            ],
        )


class BrokenBackend:
    async def retrieve(self, query):
        raise RuntimeError("database unavailable")


@pytest.mark.asyncio
async def test_retriever_filters_ticker_and_deduplicates() -> None:
    query = build_evidence_query(ticker="comi", limit=10)

    result = await NewsEvidenceRetriever(Backend()).retrieve(query)

    assert result.status is DataAvailability.AVAILABLE
    assert [item.evidence_id for item in result.items] == ["1"]


@pytest.mark.asyncio
async def test_retriever_reports_backend_failure_without_leaking_exception() -> None:
    result = await NewsEvidenceRetriever(BrokenBackend()).retrieve(
        build_evidence_query(ticker="COMI")
    )

    assert result.status is DataAvailability.UNAVAILABLE
    assert result.items == []
    assert result.limitations == ["News evidence retrieval is unavailable."]


def test_query_limit_is_bounded_by_contract() -> None:
    with pytest.raises(ValueError):
        build_evidence_query(limit=0)


@pytest.mark.asyncio
async def test_news_agent_backend_maps_only_traceable_similar_news():
    article_id = uuid4()

    class NewsTools:
        def retrieve_similar_news(self, request):
            assert request.ticker == "COMI"
            assert request.end_at is not None and request.end_at.tzinfo is not None
            return RetrievalToolResponse(
                status=ToolStatus.OK,
                data=RetrievalData(
                    coverage_status="ok",
                    items=[
                        SimilarNewsItem(
                            article_id=article_id,
                            source_url="https://news.example/item",
                            source_name="EGX source",
                            published_at=datetime(2026, 11, 24, tzinfo=UTC),
                            event_type="earnings",
                            similarity_score=0.8,
                            evidence_text="Company reported a filing.",
                        )
                    ],
                ),
                trace_id=uuid4(),
                generated_at=datetime.now(UTC),
            )

    result = await NewsEvidenceRetriever(NewsToolsEvidenceBackend(NewsTools())).retrieve(
        build_evidence_query(ticker="comi", as_of=date(2026, 11, 24))
    )

    assert result.status is DataAvailability.AVAILABLE
    assert len(result.items) == 1
    assert result.items[0].evidence_id == str(article_id)
    assert result.items[0].article_id == article_id
    assert result.items[0].source_url == "https://news.example/item"

