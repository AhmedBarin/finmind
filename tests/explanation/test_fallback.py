from __future__ import annotations

from app.explanation.constants import ARABIC_RISK_DISCLAIMER
from app.explanation.fallback import build_safe_stock_qa_fallback
from app.explanation.schemas import StockQARequest
from app.explanation.validator import find_recommendation_language


def test_fallback_is_deterministic_and_contains_no_unverified_numbers() -> None:
    request = StockQARequest(question="ما بيانات السهم؟", tickers=["COMI.CA"])
    results = {
        "get_price_history": [
            {
                "status": "unavailable",
                "limitations": ["تعذر التحقق من حداثة الأسعار."],
            }
        ]
    }

    first = build_safe_stock_qa_fallback(request, results)
    second = build_safe_stock_qa_fallback(request, results)

    assert first == second
    assert first.facts == []
    assert not any(char.isdigit() for char in first.answer)
    assert first.disclaimer == ARABIC_RISK_DISCLAIMER
    assert "تعذر التحقق من حداثة الأسعار." in first.limitations


def test_fallback_drops_recommendation_language_from_tool_limitations() -> None:
    request = StockQARequest(question="ما بيانات السهم؟", tickers=["COMI.CA"])
    draft = build_safe_stock_qa_fallback(
        request,
        {"get_price_history": [{"status": "partial", "limitations": ["buy now", "missing prices"]}]},
    )

    assert all(not find_recommendation_language(value) for value in draft.limitations)
    assert "missing prices" in draft.limitations
