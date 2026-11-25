"""Deterministic Stock Q&A fallback content."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
import json
import re
from typing import Any

from app.explanation.constants import ARABIC_RISK_DISCLAIMER, ENGLISH_RISK_DISCLAIMER
from app.explanation.schemas import ExplanationLanguage, StockQAFact, StockQARequest
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
    """Answer from exact stored fields when generation cannot be grounded."""
    limitations = _tool_limitations(tool_results)
    language = request.language
    disclaimer = (
        ARABIC_RISK_DISCLAIMER
        if language is ExplanationLanguage.ARABIC
        else ENGLISH_RISK_DISCLAIMER
    )
    facts: list[StockQAFact] = []
    snapshot_answer = _grounded_snapshot_answer(request, tool_results, facts)
    glossary_answer = _grounded_glossary_answer(request, tool_results, facts)
    parts = [part for part in (snapshot_answer, glossary_answer) if part]
    if snapshot_answer and glossary_answer:
        parts.append(
            "هذه المؤشرات تساعد على وصف الحالة الفنية، لكنها لا تكفي وحدها لاتخاذ قرار دخول."
            if language is ExplanationLanguage.ARABIC
            else "These indicators help describe technical conditions, but are not enough on their own to make an entry decision."
        )
    answer = " ".join(parts)
    if not answer:
        answer = (
            "لم أجد قيمة محفوظة تكفي للإجابة عن هذا السؤال. أعد صياغة السؤال باسم المؤشر أو اطلب حالة السهم."
            if language is ExplanationLanguage.ARABIC
            else "I could not find a stored value that answers this question. Try naming an indicator or asking for the stock's technical state."
        )
        limitations.append(
            "تعذر تكوين إجابة موثوقة من البيانات المتاحة؛ راجع القيود والبيانات المنظمة."
        )
    return StockQADraft(
        answer=answer,
        facts=facts,
        limitations=list(dict.fromkeys(limitations))[:20],
        disclaimer=disclaimer,
    )


def _snapshot_payloads(
    tool_results: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[tuple[str, Mapping[str, Any]]]:
    snapshots: list[tuple[str, Mapping[str, Any]]] = []
    for tool_name in ("get_technical_snapshot", "get_snapshot_history"):
        for result in tool_results.get(tool_name, ()):
            payload = result.get("payload")
            if not isinstance(payload, Mapping):
                continue
            if tool_name == "get_technical_snapshot":
                snapshots.append((tool_name, payload))
            else:
                rows = payload.get("snapshots")
                if isinstance(rows, list):
                    snapshots.extend(
                        (tool_name, row) for row in rows if isinstance(row, Mapping)
                    )
    return snapshots


def _grounded_snapshot_answer(
    request: StockQARequest,
    tool_results: Mapping[str, Sequence[Mapping[str, Any]]],
    facts: list[StockQAFact],
) -> str:
    question = request.question.casefold()
    is_arabic = request.language is ExplanationLanguage.ARABIC
    trend_question = bool(
        re.search(
            r"\b(?:trend|trending|state|status|regime)\b|اتجاه|ترند|حالة|السهم|سهم|صاعد|هابط|كيف",
            question,
        )
    )
    momentum_question = bool(
        re.search(r"\b(?:momentum|rsi|macd|adx)\b|زخم|rsi|macd|adx", question)
    )
    volume_question = bool(re.search(r"\bvolume\b|حجم", question))
    overview_question = bool(
        re.search(r"\b(?:overview|summary|summarize|about)\b|نظرة|ملخص|نبذة", question)
    )
    indicator_question = bool(
        re.search(r"\b(?:indicator|indicators|rsi|macd|adx|atr|sma)\b|مؤشر|قراءة|قيمة", question)
    )
    requested: list[tuple[str, Any, str]] = []

    for source_tool, snapshot in _snapshot_payloads(tool_results):
        indicators = snapshot.get("indicators") or {}
        scores = snapshot.get("scores") or {}
        families = scores.get("family_scores") or {}

        def add(label: str, value: Any) -> None:
            if value is None:
                return
            if any(existing[0] == label for existing in requested):
                return
            requested.append((label, value, source_tool))

        if overview_question:
            add("الحالة الفنية" if is_arabic else "Technical regime", snapshot.get("regime") or scores.get("regime"))
            add("حالة المخاطر" if is_arabic else "Risk label", snapshot.get("risk_label") or scores.get("risk_label"))
            add("درجة الإعداد" if is_arabic else "Setup score", snapshot.get("setup_score"))
            for key, label in (
                ("rsi14", "RSI14"), ("macd", "MACD"), ("adx14", "ADX14"),
                ("atr14", "ATR14"), ("sma20", "SMA20"), ("sma50", "SMA50"),
            ):
                top_level_key = {
                    "rsi14": "rsi",
                    "atr14": "atr",
                    "sma20": "sma_20",
                    "sma50": "sma_50",
                }.get(key, key)
                add(label, indicators.get(key, snapshot.get(top_level_key)))
            for family, label in (
                ("trend", "Trend"), ("momentum", "Momentum"),
                ("volume", "Volume"), ("support_resistance", "Support/resistance"),
            ):
                family_score = families.get(family)
                if isinstance(family_score, Mapping):
                    add(f"{label} score", family_score.get("score"))
                    add(f"{label} state", family_score.get("state"))

        if trend_question and not overview_question:
            add("الحالة الفنية" if is_arabic else "Technical regime", snapshot.get("regime") or scores.get("regime"))
            trend_score = families.get("trend")
            if isinstance(trend_score, Mapping):
                add("درجة الاتجاه" if is_arabic else "Trend score", trend_score.get("score"))
                add("حالة الاتجاه" if is_arabic else "Trend signal state", trend_score.get("state"))
            add("ADX14", indicators.get("adx14"))

        if momentum_question and not overview_question:
            add("RSI14", indicators.get("rsi14", snapshot.get("rsi")))
            for key in ("macd", "macd_signal", "macd_histogram", "adx14"):
                add(key.upper(), indicators.get(key))
            momentum_score = families.get("momentum")
            if isinstance(momentum_score, Mapping):
                add("درجة الزخم" if is_arabic else "Momentum score", momentum_score.get("score"))
                add("حالة الزخم" if is_arabic else "Momentum signal state", momentum_score.get("state"))

        if volume_question and not overview_question:
            volume_score = families.get("volume")
            if isinstance(volume_score, Mapping):
                add("درجة الحجم" if is_arabic else "Volume score", volume_score.get("score"))
                add("حالة الحجم" if is_arabic else "Volume signal state", volume_score.get("state"))
            for key, value in indicators.items():
                if "volume" in str(key).casefold() or "حجم" in str(key):
                    add(str(key), value)

        if indicator_question and not overview_question and not requested:
            for key in ("rsi14", "macd", "adx14", "atr14", "sma20", "sma50"):
                add(key.upper(), indicators.get(key))

        if not overview_question and not trend_question and not momentum_question and not volume_question and not indicator_question:
            add("الحالة الفنية" if is_arabic else "Technical regime", snapshot.get("regime") or scores.get("regime"))
            add("RSI14", indicators.get("rsi14", snapshot.get("rsi")))
            add("حالة المخاطر" if is_arabic else "Risk label", snapshot.get("risk_label") or scores.get("risk_label"))

    if not requested:
        return ""
    ticker = request.tickers[0]
    rendered: list[str] = []
    for label, value, source_tool in requested[:10]:
        rendered_value = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        facts.append(
            StockQAFact(label=label, value=rendered_value, source_tool=source_tool)
        )
        rendered.append(f"{label}: {rendered_value}")
    if is_arabic:
        return f"لقطة {ticker} الفنية المسجلة: " + "، ".join(rendered) + "."
    return f"Stored technical snapshot for {ticker}: " + "; ".join(rendered) + "."


def _grounded_glossary_answer(
    request: StockQARequest,
    tool_results: Mapping[str, Sequence[Mapping[str, Any]]],
    facts: list[StockQAFact],
) -> str:
    is_arabic = request.language is ExplanationLanguage.ARABIC
    answers: list[str] = []
    for result in tool_results.get("get_indicator_glossary", ()):
        definition = result.get("definition")
        if not isinstance(definition, Mapping):
            continue
        name = str(definition.get("name") or "indicator")
        explanation = definition.get("explanation_ar" if is_arabic else "explanation_en")
        note = definition.get("note_ar" if is_arabic else "note_en")
        if not isinstance(explanation, str) or not explanation:
            continue
        value = f"{explanation} {note}".strip() if note else explanation
        facts.append(
            StockQAFact(
                label=name,
                value=value,
                source_tool="get_indicator_glossary",
            )
        )
        answers.append(f"{name}: {value}")
    return " ".join(answers)
