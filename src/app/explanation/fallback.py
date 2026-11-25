"""Deterministic Stock Q&A fallback content."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

from app.explanation.constants import ARABIC_RISK_DISCLAIMER, ENGLISH_RISK_DISCLAIMER
from app.explanation.schemas import ExplanationLanguage, StockQARequest
from app.explanation.validator import StockQADraft, find_recommendation_language


def _tool_limitations(
    tool_results: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[str]:
    limitations: list[str] = []
    for results in tool_results.values():
        for result in results:
            values = result.get("limitations", [])
            if isinstance(values, list):
                limitations.extend(
                    value[:500]
                    for value in values
                    if isinstance(value, str)
                    and not find_recommendation_language(value)
                )
    return list(dict.fromkeys(limitations))[:18]


def build_safe_stock_qa_fallback(
    request: StockQARequest,
    tool_results: Mapping[str, Sequence[Mapping[str, Any]]],
) -> StockQADraft:
    """Return a short, non-numeric answer that does not infer missing facts."""
    limitations = _tool_limitations(tool_results)
    limitations.append("تعذر تكوين إجابة موثوقة من البيانات المتاحة؛ راجع القيود والبيانات المنظمة.")
    disclaimer = (
        ARABIC_RISK_DISCLAIMER
        if request.language is ExplanationLanguage.ARABIC
        else ENGLISH_RISK_DISCLAIMER
    )
    answer = (
        "تعذر تكوين إجابة موثوقة من البيانات المتاحة. تتضمن النتيجة القيود "
        "وحالة توفر البيانات التي أمكن استرجاعها."
        if request.language is ExplanationLanguage.ARABIC
        else "A reliable answer could not be formed from the available data. The result includes the limitations and availability of the retrieved data."
    )
    return StockQADraft(
        answer=answer,
        facts=[],
        limitations=list(dict.fromkeys(limitations))[:20],
        disclaimer=disclaimer,
    )
