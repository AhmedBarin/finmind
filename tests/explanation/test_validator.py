from __future__ import annotations

from app.explanation.constants import ARABIC_RISK_DISCLAIMER
from app.explanation.schemas import StockQAFact, StockQARequest
from app.explanation.validator import (
    StockQADraft,
    find_recommendation_language,
    validate_stock_qa_draft,
)


def _request(**overrides):
    values = {"question": "ما قيمة RSI؟", "tickers": ["COMI.CA"]}
    values.update(overrides)
    return StockQARequest(**values)


def _tools():
    return {
        "get_technical_snapshot": [
            {
                "status": "available",
                "data_date": "2026-11-24",
                "freshness_status": "fresh",
                "trading_days_old": 0,
                "payload": {"ticker": "COMI.CA", "indicators": {"rsi14": 54.2}},
            }
        ]
    }


def _valid_draft(**overrides):
    values = {
        "answer": "تُظهر البيانات المسجلة أن قراءة RSI هي 54.2.",
        "facts": [
            StockQAFact(
                label="RSI14",
                value="54.2",
                source_tool="get_technical_snapshot",
            )
        ],
        "limitations": [],
        "disclaimer": ARABIC_RISK_DISCLAIMER,
    }
    values.update(overrides)
    return StockQADraft(**values)


def test_grounded_arabic_numeric_claim_and_fact_pass() -> None:
    errors = validate_stock_qa_draft(
        _valid_draft(), request=_request(), tool_results=_tools()
    )

    assert errors == []


def test_unsupported_numeric_claim_fails() -> None:
    draft = _valid_draft(answer="قيمة RSI هي 55.2.")

    errors = validate_stock_qa_draft(draft, request=_request(), tool_results=_tools())

    assert "unsupported_numeric_claim" in errors


def test_arabic_digits_are_checked_against_tool_numbers() -> None:
    draft = _valid_draft(answer="قيمة RSI هي ٥٤٫٢.")

    errors = validate_stock_qa_draft(draft, request=_request(), tool_results=_tools())

    assert "unsupported_numeric_claim" not in errors


def test_date_components_are_not_mistaken_for_financial_numeric_claims() -> None:
    draft = _valid_draft(answer="تاريخ البيانات هو 2026-11-24، وقيمة RSI هي 54.2.")

    errors = validate_stock_qa_draft(draft, request=_request(), tool_results=_tools())

    assert errors == []


def test_missing_or_wrong_tool_citation_fails() -> None:
    fact = StockQAFact(label="RSI14", value="54.2", source_tool="get_price_history")
    draft = _valid_draft(facts=[fact])

    errors = validate_stock_qa_draft(draft, request=_request(), tool_results=_tools())

    assert "fact_source_tool_not_used" in errors
    assert "fact_not_grounded_in_source_tool" in errors


def test_missing_disclaimer_fails() -> None:
    draft = _valid_draft(disclaimer="شرح عام للبيانات.")

    errors = validate_stock_qa_draft(draft, request=_request(), tool_results=_tools())

    assert "required_disclaimer_missing" in errors


def test_recommendation_terms_are_blocked_without_substring_false_positive() -> None:
    assert find_recommendation_language("You should BUY this")
    assert find_recommendation_language("Buying shares is advised")
    assert find_recommendation_language("The stockholder should hold")
    assert find_recommendation_language("أنصح بشراء السهم")
    assert not find_recommendation_language("The buyer reviewed the data")
    assert not find_recommendation_language("المعلومات الوصفية متاحة")


def test_missing_data_date_or_freshness_is_explicitly_invalid() -> None:
    tools = {
        "get_price_history": [
            {"status": "available", "data_date": None, "payload": {"close": 12}}
        ]
    }

    errors = validate_stock_qa_draft(
        _valid_draft(), request=_request(), tool_results=tools
    )

    assert "data_date_missing" in errors
    assert "freshness_missing" in errors
