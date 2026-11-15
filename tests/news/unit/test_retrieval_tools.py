from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.news_agent.retrieval_schemas import (
    AnnualReportEvidenceRequest,
    SimilarNewsRequest,
)
from app.agents.news_agent.retrieval_tools import NewsRetrievalTools
from app.news.retrieval import InMemoryNewsVectorIndex, NewsChunk


def indexed_chunk(text, *, document_type=None, ticker="COMI", article_id=None, event_type="earnings_results"):
    article_id = article_id or uuid4()
    return NewsChunk(
        chunk_id=str(uuid4()), article_id=article_id, text=text,
        metadata={
            "article_id": str(article_id), "ticker_links": [ticker], "company_ids": [],
            "source_url": "https://example.test/news", "source_name": "Example",
            "published_at": "2026-11-10T12:00:00+00:00", "event_type": event_type,
            "document_type": document_type, "document_title": "Annual Report",
            "fiscal_year": 2025, "content_rights": "full_text",
        },
    )


def test_annual_report_returns_only_report_evidence_with_provenance():
    index = InMemoryNewsVectorIndex()
    index.upsert(chunks=[
        indexed_chunk("Revenue and profit increased", document_type="annual_report"),
        indexed_chunk("Routine news update", document_type=None),
    ])
    response = NewsRetrievalTools(index).get_annual_report_evidence(
        AnnualReportEvidenceRequest(ticker="COMI", query="profit", fiscal_year=2025)
    )
    assert response.status == "ok"
    assert len(response.data.items) == 1
    assert response.data.items[0].document_type == "annual_report"
    assert response.data.items[0].source_url == "https://example.test/news"


def test_annual_report_missing_is_not_found_not_fabricated():
    response = NewsRetrievalTools(InMemoryNewsVectorIndex()).get_annual_report_evidence(
        AnnualReportEvidenceRequest(ticker="COMI", query="profit")
    )
    assert response.status == "not_found"
    assert response.data.items == []


def test_similar_news_filters_by_ticker_and_deduplicates_articles():
    index = InMemoryNewsVectorIndex()
    first = uuid4()
    index.upsert(chunks=[
        indexed_chunk("earnings profit growth", article_id=first),
        indexed_chunk("earnings profit detail", article_id=first),
        indexed_chunk("earnings profit other company", ticker="SWDY"),
    ])
    response = NewsRetrievalTools(index).retrieve_similar_news(
        SimilarNewsRequest(query="earnings profit", ticker="COMI", limit=5)
    )
    assert response.status == "ok"
    assert len(response.data.items) == 1
    assert response.data.items[0].article_id == first
    assert any("not a probability" in warning for warning in response.warnings)


def test_similar_news_reports_unavailable_index():
    class BrokenIndex:
        def query(self, text, *, limit=5):
            raise RuntimeError("offline")

    response = NewsRetrievalTools(BrokenIndex()).retrieve_similar_news(
        SimilarNewsRequest(query="earnings")
    )
    assert response.status == "unavailable"
    assert response.errors == ["offline"]


def test_retrieval_requests_are_bounded_and_timezone_safe():
    with pytest.raises(ValidationError):
        AnnualReportEvidenceRequest(ticker="COMI", query="x", limit=11)
    with pytest.raises(ValidationError):
        SimilarNewsRequest(query="x", start_at=datetime(2026, 1, 1))
