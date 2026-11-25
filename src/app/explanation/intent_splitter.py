"""Deterministic intent classification for descriptive and recommendation questions."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from enum import StrEnum


class QuestionIntent(StrEnum):
    DESCRIPTIVE = "descriptive"
    RECOMMENDATION = "recommendation"
    MIXED = "mixed"
    AMBIGUOUS = "ambiguous"


@dataclass(frozen=True, slots=True)
class IntentSplit:
    """Classification and source-preserving question parts for the orchestrator."""

    intent: QuestionIntent
    descriptive_question: str | None = None
    recommendation_question: str | None = None


_RECOMMENDATION_RE = re.compile(
    r"(?<![a-z])(?:buy|buying|bought|sell|selling|sold|hold|holding|avoid|purchase|"
    r"recommend|recommendation)(?![a-z])"
    r"|\b(?:should\s+i|can\s+i\s+enter|should\s+i\s+enter|"
    r"would\s+you\s+recommend|is\s+it\s+better\s+to)\b"
    r"|(?:شراء|اشتر|اشتري|اشترى|بيع|بع|يبيع|تبيع|احتفظ|تجنب|انصح|اوصي|توصية|"
    r"هل\s+يمكنني\s+الدخول|هل\s+استطيع\s+الدخول|ادخل|أدخل)",
    re.IGNORECASE,
)
_DESCRIPTIVE_RE = re.compile(
    r"(?<![a-z])(?:what|which|how|when|show|explain|describe|value|price|history|"
    r"snapshot|indicator|rsi|macd|sma|atr|adx|volume|data)(?![a-z])"
    r"|(?:ما|ماذا|كيف|كم|متى|اعرض|اشرح|قيمة|سعر|تاريخ|بيانات|لقطة|مؤشر|حجم)",
    re.IGNORECASE,
)
_CLAUSE_SPLIT_RE = re.compile(
    r"\s+(?:and|also)\s+|\s+(?:و?هل|وهل|او هل|أو هل)\s+|[،,؛;]\s*|(?<=[؟?])\s+",
    re.IGNORECASE,
)


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold()
    value = value.replace("أ", "ا").replace("إ", "ا").replace("آ", "ا").replace("ى", "ي")
    return value


def _classify_clause(clause: str) -> QuestionIntent:
    normalized = _normalize(clause)
    has_recommendation = _RECOMMENDATION_RE.search(normalized) is not None
    has_descriptive = _DESCRIPTIVE_RE.search(normalized) is not None
    if has_recommendation and has_descriptive:
        return QuestionIntent.MIXED
    if has_recommendation:
        return QuestionIntent.RECOMMENDATION
    if has_descriptive:
        return QuestionIntent.DESCRIPTIVE
    return QuestionIntent.AMBIGUOUS


def split_question_intent(question: str) -> IntentSplit:
    """Classify and split a question without invoking models or altering its text.

    Recommendation-only content is returned for the Recommendation Engine. This
    function only routes text; it does not generate a recommendation or answer.
    """
    source = question.strip()
    if not source:
        return IntentSplit(intent=QuestionIntent.AMBIGUOUS)

    descriptive_parts: list[str] = []
    recommendation_parts: list[str] = []
    ambiguous_parts: list[str] = []
    for clause in _CLAUSE_SPLIT_RE.split(source):
        clause = clause.strip()
        if not clause:
            continue
        intent = _classify_clause(clause)
        if intent is QuestionIntent.DESCRIPTIVE:
            descriptive_parts.append(clause)
        elif intent is QuestionIntent.RECOMMENDATION:
            recommendation_parts.append(clause)
        elif intent is QuestionIntent.MIXED:
            # Keep an indivisible clause intact so neither part is silently lost.
            descriptive_parts.append(clause)
            recommendation_parts.append(clause)
        else:
            ambiguous_parts.append(clause)

    if ambiguous_parts:
        # Do not route partial text when any clause still needs user clarification.
        return IntentSplit(intent=QuestionIntent.AMBIGUOUS)
    if descriptive_parts and recommendation_parts:
        intent = QuestionIntent.MIXED
    elif recommendation_parts:
        intent = QuestionIntent.RECOMMENDATION
    elif descriptive_parts and not ambiguous_parts:
        intent = QuestionIntent.DESCRIPTIVE
    else:
        intent = QuestionIntent.AMBIGUOUS

    return IntentSplit(
        intent=intent,
        descriptive_question=" ".join(descriptive_parts) or None,
        recommendation_question=" ".join(recommendation_parts) or None,
    )
