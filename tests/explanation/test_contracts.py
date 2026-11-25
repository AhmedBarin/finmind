from datetime import datetime, timezone
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.explanation.constants import ARABIC_RISK_DISCLAIMER
from app.explanation.schemas import (
    DataAvailability,
    EvidenceItem,
    EvidenceQuery,
    EvidenceResult,
    StockQARequest,
    StockQAResponse,
)


def test_evidence_item_normalizes_ticker_and_preserves_provenance() -> None:
    item = EvidenceItem(
        evidence_id="article-1",
        article_id=uuid4(),
        title="CIB results",
        ticker=" comi ",
        source_url="https://example.test/article",
    )

    assert item.ticker == "COMI"
    assert item.source_url == "https://example.test/article"


def test_evidence_query_has_bounded_limit_and_normalized_ticker() -> None:
    query = EvidenceQuery(ticker="comi", query_text="earnings", limit=20)

    assert query.ticker == "COMI"
    assert query.limit == 20


def test_evidence_result_keeps_missingness_explicit() -> None:
    result = EvidenceResult(
        status=DataAvailability.NOT_FOUND,
        limitations=["No permitted article matched the ticker."],
    )

    assert result.status is DataAvailability.NOT_FOUND
    assert result.items == []


def test_stock_qa_request_normalizes_and_deduplicates_tickers() -> None:
    request = StockQARequest(
        question="Explain the latest indicators", tickers=["comi", "SWDY"]
    )

    assert request.tickers == ["COMI", "SWDY"]
    assert request.max_tool_calls == 5
    assert request.language.value == "en"


def test_stock_qa_language_follows_arabic_or_english_question_unless_explicit() -> None:
    arabic = StockQARequest(question="ما حالة السهم؟", tickers=["COMI"])
    english = StockQARequest(question="What is the stock state?", tickers=["COMI"])
    explicit = StockQARequest(
        question="What is the stock state?", tickers=["COMI"], language="ar"
    )

    assert arabic.language.value == "ar"
    assert english.language.value == "en"
    assert explicit.language.value == "ar"


def test_stock_qa_request_rejects_duplicate_tickers() -> None:
    with pytest.raises(ValidationError, match="tickers must be unique"):
        StockQARequest(question="Explain", tickers=["COMI", "comi"])


def test_stock_qa_response_has_explicit_date_and_disclaimer() -> None:
    response = StockQAResponse(
        tickers=["COMI"],
        data_date=None,
        answer="لا توجد بيانات حديثة كافية.",
        disclaimer=ARABIC_RISK_DISCLAIMER,
        generated_at=datetime.now(timezone.utc),
        status="not_found",
    )

    assert response.explanation_type == "stock_qa"
    assert response.status == "not_found"
    assert response.data_date is None
