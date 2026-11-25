from __future__ import annotations

import pytest

from app.explanation.constants import ARABIC_RISK_DISCLAIMER
from app.explanation.schemas import StockQAFact, StockQARequest
from app.explanation.validator import (
    StockQADraft,
    find_recommendation_language,
    validate_stock_qa_draft,
)


def _request() -> StockQARequest:
    return StockQARequest(question="ما قراءة RSI؟", tickers=["COMI"])


def _evidence() -> dict[str, list[dict[str, object]]]:
    return {
        "get_technical_snapshot": [
            {
                "status": "available",
                "data_date": "2026-11-24",
                "freshness_status": "fresh",
                "payload": {"ticker": "COMI", "indicators": {"rsi14": 54.2}},
            }
        ]
    }


def _draft(**overrides) -> StockQADraft:
    values = {
        "answer": "تُظهر البيانات قراءة RSI14 مقدارها 54.2.",
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


def test_fabricated_fact_label_is_rejected_even_when_number_is_grounded() -> None:
    draft = _draft(
        facts=[
            StockQAFact(
                label="Institutional buying pressure",
                value="54.2",
                source_tool="get_technical_snapshot",
            )
        ]
    )

    errors = validate_stock_qa_draft(draft, request=_request(), tool_results=_evidence())

    assert "fact_label_not_grounded_in_source_tool" in errors


@pytest.mark.parametrize(
    "claim",
    [
        "Buy the stock.",
        "You should be buying this stock.",
        "Avoid the stock.",
        "أنصح بشراء السهم.",
        "تجنب السهم.",
        "احتفظ بالسهم.",
    ],
)
def test_english_and_arabic_recommendation_phrases_are_detected(claim: str) -> None:
    assert find_recommendation_language(claim)


def test_safe_explanatory_words_do_not_trigger_recommendation_filter() -> None:
    assert not find_recommendation_language("The buyer reviewed the data.")
    assert not find_recommendation_language("المعلومات الوصفية متاحة.")


def test_answer_with_unsupported_numbers_and_recommendation_is_rejected() -> None:
    draft = _draft(answer="قيمة RSI هي 99.1؛ اشتر السهم.")

    errors = validate_stock_qa_draft(draft, request=_request(), tool_results=_evidence())

    assert "unsupported_numeric_claim" in errors
    assert "recommendation_language_detected" in errors
