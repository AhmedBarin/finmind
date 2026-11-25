"""Grounding and safety validation for Stock Q&A drafts."""

from __future__ import annotations

import json
import re
import unicodedata
from collections.abc import Mapping, Sequence
from decimal import Decimal, InvalidOperation
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.explanation.constants import (
    ARABIC_RISK_DISCLAIMER,
    ENGLISH_RISK_DISCLAIMER,
    RECOMMENDATION_TERMS,
)
from app.explanation.schemas import ExplanationLanguage, StockQAFact, StockQARequest


MAX_ANSWER_CHARS = 4000
MAX_FACTS = 30
MAX_LIMITATIONS = 20

_ARABIC_MARKS = re.compile(r"[\u064B-\u065F\u0670\u06D6-\u06ED]")
_ISO_DATE_RE = re.compile(
    r"\b\d{4}-\d{2}-\d{2}(?:[T ][0-9:.+\-Z]+)?\b", re.IGNORECASE
)
_UUID_RE = re.compile(
    r"\b[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}\b",
    re.IGNORECASE,
)
_NUMBER_RE = re.compile(
    r"(?<![\w.])[+-]?(?:\d{1,3}(?:[,\u066C]\d{3})+|\d+)"
    r"(?:[.\u066B]\d+)?%?(?!\w)"
)
_ARABIC_NUMERALS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_ARABIC_DIGIT_SEPARATORS = str.maketrans({"٫": ".", "٬": ","})
_ARABIC_WORD_RE = re.compile(r"[\u0621-\u064A\u066E-\u06D3]+")
_ARABIC_RECOMMENDATION_WORDS = frozenset(
    {
        "شراء", "الشراء", "بشراء", "بالشراء", "اشتر", "اشترى", "اشتري", "اشتروا", "تشتري", "يشتري",
        "بيع", "البيع", "بع", "يبيع", "تبيع", "بيعوا", "احتفظ", "الاحتفاظ",
        "ببيع", "بالبيع", "احتفظي", "احتفظوا", "تجنب", "تجنبوا", "تجنبي", "تجنبها", "انصح", "انصحك",
        "اوصي", "اوصيك", "يوصي", "توصية", "التوصية", "نصيحة", "نصيحتي",
    }
)
_ENGLISH_RECOMMENDATION_WORDS = frozenset({"recommend", "recommends", "recommended", "recommendation", "recommendations"})
_ENGLISH_ACTION_PATTERNS = (
    r"(?<![a-z])buy(?:s|ing|bought)?(?![a-z])",
    r"(?<![a-z])sell(?:s|ing|sold)?(?![a-z])",
    r"(?<![a-z])hold(?:s|ing|ings|held)?(?![a-z])",
    r"(?<![a-z])avoid(?:s|ed|ing)?(?![a-z])",
    r"(?<![a-z])purchase(?:s|d|ing)?(?![a-z])",
)


class StockQADraft(BaseModel):
    """LLM-produced content fields; system-owned metadata is added afterward."""

    model_config = ConfigDict(extra="forbid")

    answer: str = Field(min_length=1, max_length=MAX_ANSWER_CHARS)
    facts: list[StockQAFact] = Field(default_factory=list, max_length=MAX_FACTS)
    limitations: list[str] = Field(default_factory=list, max_length=MAX_LIMITATIONS)
    disclaimer: str = Field(min_length=1, max_length=1000)


def _normalize_text(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).translate(_ARABIC_NUMERALS)
    value = _ARABIC_MARKS.sub("", value)
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا")
    value = value.replace("ى", "ي")
    return re.sub(r"\s+", " ", value).strip().casefold()


def find_recommendation_language(text: str) -> list[str]:
    """Return blocked terms using whole-word/phrase matching, not substrings."""
    normalized = _normalize_text(text)
    found: set[str] = set()
    for term in RECOMMENDATION_TERMS:
        normalized_term = _normalize_text(term)
        if not normalized_term:
            continue
        if normalized_term.isascii():
            pattern = rf"(?<![a-z]){re.escape(normalized_term)}(?![a-z])"
            if re.search(pattern, normalized, re.IGNORECASE):
                found.add(term)
    for term in _ENGLISH_RECOMMENDATION_WORDS:
        if re.search(rf"(?<![a-z]){re.escape(term)}(?![a-z])", normalized):
            found.add(term)
    for pattern in _ENGLISH_ACTION_PATTERNS:
        match = re.search(pattern, normalized)
        if match:
            found.add(match.group())
    arabic_tokens = set(_ARABIC_WORD_RE.findall(normalized))
    found.update(arabic_tokens & _ARABIC_RECOMMENDATION_WORDS)
    # Also cover common two-token advisory phrasing while preserving boundaries.
    if re.search(r"(?<!\w)انصح\s+(?:ب|لك|لكم|بان)(?!\w)", normalized):
        found.add("أنصح بـ")
    return sorted(found)


def _canonical_number(value: str) -> str | None:
    normalized = (
        unicodedata.normalize("NFKC", value)
        .translate(_ARABIC_NUMERALS)
        .translate(_ARABIC_DIGIT_SEPARATORS)
        .replace("%", "")
        .replace(",", "")
        .strip()
    )
    try:
        number = Decimal(normalized)
    except InvalidOperation:
        return None
    if not number.is_finite():
        return None
    normalized_number = number.normalize()
    return format(normalized_number, "f")


def _numeric_claims(value: str) -> set[str]:
    value = _ISO_DATE_RE.sub(" ", value)
    value = _UUID_RE.sub(" ", value)
    value = value.translate(_ARABIC_NUMERALS).translate(_ARABIC_DIGIT_SEPARATORS)
    claims: set[str] = set()
    for match in _NUMBER_RE.finditer(value):
        canonical = _canonical_number(match.group())
        if canonical is not None:
            claims.add(canonical)
    return claims


def _serialize_tool_results(tool_results: Mapping[str, Sequence[Mapping[str, Any]]]) -> str:
    return json.dumps(tool_results, ensure_ascii=False, sort_keys=True, default=str)


def _normalize_grounding_text(value: str) -> str:
    return re.sub(r"\s+", " ", unicodedata.normalize("NFKC", value)).strip().casefold()


def validate_stock_qa_draft(
    draft: StockQADraft,
    *,
    request: StockQARequest,
    tool_results: Mapping[str, Sequence[Mapping[str, Any]]],
) -> list[str]:
    """Return stable validation errors for unsupported or unsafe output."""
    errors: list[str] = []
    expected_disclaimer = (
        ARABIC_RISK_DISCLAIMER
        if request.language is ExplanationLanguage.ARABIC
        else ENGLISH_RISK_DISCLAIMER
    )
    if expected_disclaimer not in draft.disclaimer:
        errors.append("required_disclaimer_missing")

    risky_terms = find_recommendation_language(draft.answer)
    for fact in draft.facts:
        risky_terms.extend(find_recommendation_language(fact.label))
        risky_terms.extend(find_recommendation_language(fact.value))
    if risky_terms:
        errors.append("recommendation_language_detected")

    if any(fact.source_tool not in tool_results for fact in draft.facts):
        errors.append("fact_source_tool_not_used")

    requires_market_freshness = any(
        name != "get_indicator_glossary"
        and any(
            result.get("status") in {"available", "stale", "partial"}
            for result in results
        )
        for name, results in tool_results.items()
    )
    if requires_market_freshness:
        data_results = [
            result
            for name, results in tool_results.items()
            if name != "get_indicator_glossary"
            for result in results
        ]
        if not any(result.get("data_date") for result in data_results):
            errors.append("data_date_missing")
        if any(not result.get("freshness_status") for result in data_results):
            errors.append("freshness_missing")

    all_claims = _numeric_claims(draft.answer)
    for fact in draft.facts:
        all_claims.update(_numeric_claims(fact.label))
        all_claims.update(_numeric_claims(fact.value))
    evidence_claims = _numeric_claims(_serialize_tool_results(tool_results))
    if not all_claims.issubset(evidence_claims):
        errors.append("unsupported_numeric_claim")

    for fact in draft.facts:
        sources = tool_results.get(fact.source_tool, ())
        source_text = _serialize_tool_results({fact.source_tool: sources})
        source_claims = _numeric_claims(source_text)
        value_text = _normalize_grounding_text(fact.value)
        value_grounded = value_text in _normalize_grounding_text(source_text)
        numeric_grounded = _numeric_claims(fact.value).issubset(source_claims)
        if not value_grounded and not numeric_grounded:
            errors.append("fact_not_grounded_in_source_tool")
            break

    if len(draft.answer) > MAX_ANSWER_CHARS:
        errors.append("answer_too_long")
    return sorted(set(errors))

