"""Q&A Safety & Grounding Engine (REQ-033, US-011).

Provides:
- Grounding validation: every numeric claim must trace to tool outputs.
- Recommendation language rejection with retry and fallback.
- Intent splitting for mixed descriptive + advisory questions.
- Explicit handling of missing / stale data.
"""

from __future__ import annotations

import logging
import re
from typing import Any

from app.explanation.constants import RECOMMENDATION_TERMS

logger = logging.getLogger(__name__)

# ── Arabic & English recommendation patterns ────────────────────────────

# Build a compiled regex from RECOMMENDATION_TERMS (case-insensitive).
# We also include common Arabic imperative/advisory patterns.
_RECOMMENDATION_PATTERNS: list[re.Pattern[str]] = [
    re.compile(
        r"\b" + re.escape(term) + r"\b",
        re.IGNORECASE | re.UNICODE,
    )
    for term in sorted(RECOMMENDATION_TERMS, key=len, reverse=True)
]

# Additional Arabic advisory sentence patterns
_ARABIC_ADVISORY_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"أنصحك\s+بـ?", re.UNICODE),
    re.compile(r"يجب\s+عليك\s+(شراء|بيع|الشراء|البيع)", re.UNICODE),
    re.compile(r"من\s+الأفضل\s+(شراء|بيع|الشراء|البيع)", re.UNICODE),
    re.compile(r"ننصح\s+بـ?", re.UNICODE),
    re.compile(r"نوصي\s+بـ?", re.UNICODE),
]

_SAFE_FALLBACK_AR = (
    "لا يمكنني تقديم توصيات استثمارية. "
    "يمكنني فقط شرح البيانات الفنية المتاحة والمؤشرات. "
    "يُرجى استشارة مستشار مالي مرخص لاتخاذ قرارات الاستثمار."
)

_SAFE_FALLBACK_EN = (
    "I cannot provide investment recommendations. "
    "I can only explain available technical data and indicators. "
    "Please consult a licensed financial advisor for investment decisions."
)


# ═══════════════════════════════════════════════════════════════════════════
# Recommendation language detection
# ═══════════════════════════════════════════════════════════════════════════


def contains_recommendation_language(text: str) -> bool:
    """Return True if *text* contains explicit trading/investment advice."""
    for pattern in _RECOMMENDATION_PATTERNS:
        if pattern.search(text):
            return True
    for pattern in _ARABIC_ADVISORY_PATTERNS:
        if pattern.search(text):
            return True
    return False


def get_safe_fallback(language: str = "ar") -> str:
    """Return the safe fallback message in the requested language."""
    return _SAFE_FALLBACK_AR if language == "ar" else _SAFE_FALLBACK_EN


# ═══════════════════════════════════════════════════════════════════════════
# Grounding validation
# ═══════════════════════════════════════════════════════════════════════════

# Matches numbers that look like financial values (integers, decimals, percentages)
_NUMBER_PATTERN = re.compile(r"(?<!\w)(\d+(?:\.\d+)?)\s*%?(?!\w)")
# Matches indicator names that embed parameter numbers (e.g. SMA-20, SMA_50, RSI-14)
_INDICATOR_NAME_PATTERN = re.compile(r"\b[A-Za-z]+[-_]\d+\b")


def extract_numeric_claims(text: str) -> list[str]:
    """Extract all numeric tokens from a text that look like data claims."""
    cleaned = _INDICATOR_NAME_PATTERN.sub("", text)
    return _NUMBER_PATTERN.findall(cleaned)


def _collect_tool_numbers(tool_outputs: list[dict[str, Any]]) -> set[str]:
    """Recursively collect all numeric string representations from tool outputs."""
    numbers: set[str] = set()

    def _walk(obj: Any) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                for m in _NUMBER_PATTERN.findall(str(k)):
                    numbers.add(m)
                _walk(v)
        elif isinstance(obj, list):
            for v in obj:
                _walk(v)
        elif isinstance(obj, (int, float)):
            # Store multiple representations for flexible matching
            numbers.add(str(obj))
            if isinstance(obj, float):
                # Store both rounded and original
                numbers.add(f"{obj:.2f}")
                numbers.add(f"{obj:.1f}")
                numbers.add(str(int(obj)) if obj == int(obj) else str(obj))
            else:
                numbers.add(f"{obj}.0")
                numbers.add(f"{obj}.00")
        elif isinstance(obj, str):
            # Also extract numbers from string values
            for m in _NUMBER_PATTERN.findall(obj):
                numbers.add(m)

    for output in tool_outputs:
        _walk(output)
    return numbers


def validate_grounding(
    response_text: str,
    tool_outputs: list[dict[str, Any]],
) -> tuple[bool, list[str]]:
    """Verify every numeric claim in the response traces to tool outputs.

    Returns ``(is_grounded, ungrounded_claims)`` where *is_grounded* is True
    when all numbers in the response can be traced to the tool data.
    """
    claims = extract_numeric_claims(response_text)
    if not claims:
        return True, []

    known_numbers = _collect_tool_numbers(tool_outputs)
    ungrounded: list[str] = []
    for claim in claims:
        if claim not in known_numbers:
            ungrounded.append(claim)

    return len(ungrounded) == 0, ungrounded


# ═══════════════════════════════════════════════════════════════════════════
# Intent splitting
# ═══════════════════════════════════════════════════════════════════════════

# Arabic question-about-data keywords (descriptive intent)
_DESCRIPTIVE_KEYWORDS_AR = [
    "ما هو",
    "ما هي",
    "كم",
    "اشرح",
    "وضح",
    "أخبرني عن",
    "ما معنى",
    "ما المقصود",
    "ما سبب",
    "لماذا",
]
# Arabic advisory-request keywords
_ADVISORY_KEYWORDS_AR = [
    "هل أشتري",
    "هل أبيع",
    "أنصحني",
    "أوصني",
    "هل يجب",
    "ماذا أفعل",
    "هل من الأفضل",
]
_DESCRIPTIVE_KEYWORDS_EN = [
    "what is",
    "what are",
    "how much",
    "explain",
    "describe",
    "tell me about",
    "what does",
    "why did",
    "show me",
]
_ADVISORY_KEYWORDS_EN = [
    "should i buy",
    "should i sell",
    "do you recommend",
    "what should i do",
    "is it a good time",
]


def split_intent(question: str) -> tuple[str | None, str | None]:
    """Split a mixed question into (descriptive_part, advisory_part).

    Returns ``(descriptive, advisory)`` where either may be ``None`` if the
    question is purely one type.
    """
    text = question.strip()
    if not text:
        return None, None

    has_descriptive = any(kw in text.lower() for kw in _DESCRIPTIVE_KEYWORDS_EN) or any(
        kw in text for kw in _DESCRIPTIVE_KEYWORDS_AR
    )

    has_advisory = any(kw in text.lower() for kw in _ADVISORY_KEYWORDS_EN) or any(
        kw in text for kw in _ADVISORY_KEYWORDS_AR
    )

    if has_descriptive and has_advisory:
        # Both intents detected — return the full text for descriptive
        # and signal that advisory intent was detected
        return text, text
    if has_advisory and not has_descriptive:
        return None, text
    # Purely descriptive or ambiguous → treat as descriptive
    return text, None


# ═══════════════════════════════════════════════════════════════════════════
# Stale / missing data annotation
# ═══════════════════════════════════════════════════════════════════════════


def annotate_data_issues(
    tool_outputs: list[dict[str, Any]],
    language: str = "ar",
) -> list[str]:
    """Return human-readable notes about stale or missing data."""
    issues: list[str] = []
    for output in tool_outputs:
        tool_name = output.get("tool", "unknown")
        status = output.get("status", "ok")
        ticker = output.get("ticker", "")

        if status == "not_found":
            if language == "ar":
                issues.append(f"لا توجد بيانات متاحة لـ {ticker} من أداة {tool_name}.")
            else:
                issues.append(f"No data available for {ticker} from {tool_name}.")
        elif status == "stale":
            data_date = output.get("data_date", "غير معروف")
            if language == "ar":
                issues.append(
                    f"بيانات {ticker} من {tool_name} قديمة (تاريخ: {data_date})."
                )
            else:
                issues.append(
                    f"{ticker} data from {tool_name} is stale (date: {data_date})."
                )
        elif status == "unavailable":
            error_msg = output.get("error", "")
            if language == "ar":
                msg = f"تعذر الوصول إلى بيانات {ticker} من {tool_name}."
                if error_msg:
                    msg += f" ({error_msg})"
                issues.append(msg)
            else:
                msg = f"Could not access {ticker} data from {tool_name}."
                if error_msg:
                    msg += f" ({error_msg})"
                issues.append(msg)
    return issues


# ═══════════════════════════════════════════════════════════════════════════
# Correction prompt for retry
# ═══════════════════════════════════════════════════════════════════════════


CORRECTION_PROMPT_AR = (
    "الرد السابق احتوى على لغة توصيات استثمارية. "
    "أعد صياغة الإجابة لتقتصر على شرح البيانات الفنية فقط "
    "دون أي توصية أو نصيحة بالشراء أو البيع أو الاحتفاظ."
)

CORRECTION_PROMPT_EN = (
    "The previous response contained investment recommendation language. "
    "Rephrase the answer to only explain the technical data "
    "without any buy, sell, hold, or investment advice."
)


def get_correction_prompt(language: str = "ar") -> str:
    """Return the correction prompt for retrying after recommendation detection."""
    return CORRECTION_PROMPT_AR if language == "ar" else CORRECTION_PROMPT_EN
