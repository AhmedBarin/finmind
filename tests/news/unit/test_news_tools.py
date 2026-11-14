from datetime import datetime, timezone
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.agents.news_agent.schemas import (
    CompanyNewsRequest,
    RecentNewsRequest,
    SearchNewsRequest,
    NewsToolData,
    ToolStatus,
)
from app.agents.news_agent.tools import NewsAgentTools
from app.news.service import NewsService


def test_search_contract_is_bounded_and_normalizes_filters():
    request = SearchNewsRequest(
        query="  dividend  ",
        tickers=[" comi "],
        sentiments=["positive"],
        limit=20,
    )
    assert request.query == "dividend"
    assert request.tickers == ["COMI"]
    assert request.directions == ["positive"]

    with pytest.raises(ValidationError):
        SearchNewsRequest(query="x", limit=21)


def test_requests_reject_naive_or_reversed_dates():
    with pytest.raises(ValidationError):
        SearchNewsRequest(query="x", start_at=datetime(2026, 1, 1))
    with pytest.raises(ValidationError):
        SearchNewsRequest(
            query="x",
            start_at=datetime(2026, 1, 2, tzinfo=timezone.utc),
            end_at=datetime(2026, 1, 1, tzinfo=timezone.utc),
        )


def test_recent_requires_ticker_or_company():
    with pytest.raises(ValidationError):
        RecentNewsRequest()
    assert RecentNewsRequest(tickers=["COMI"]).start_at is not None


def test_tool_response_uses_common_envelope():
    data = NewsToolData(articles=[], coverage_status="no_relevant_news")
    response = NewsAgentTools._response(data)
    assert response.status == ToolStatus.NOT_FOUND
    assert response.data.coverage_status == "no_relevant_news"
    assert response.trace_id


def test_company_request_accepts_canonical_ticker_or_id():
    assert CompanyNewsRequest(ticker=" swdy ").ticker == "SWDY"
    assert CompanyNewsRequest(company_id=uuid4()).company_id


def test_tool_data_never_exposes_full_article_body():
    article = SimpleNamespace(
        id=uuid4(), title_original="Title", body_excerpt="Permitted excerpt",
        body_original="PRIVATE BODY", content_rights="metadata_only",
        published_at=None, source_url="https://example.test/a", language="en",
    )
    source = SimpleNamespace(name="Example", source_type="news",)
    row = SimpleNamespace(article=article, source=source, links=(), company_tickers=(), analysis=None)
    data = NewsService._tool_data([row])
    assert data.articles[0].snippet == "Title"
    assert "PRIVATE BODY" not in data.model_dump_json()
