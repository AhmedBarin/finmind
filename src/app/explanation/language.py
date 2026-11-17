"""Recommendation-language detection and question splitting.

The exact Arabic lexicon is still NEEDS CLARIFICATION in the plan; this is a
deliberately conservative provisional list. Single words are matched as whole
tokens (so descriptive terms such as "ضغط بيعي" do not match "بيع"), multi-word
phrases as substrings, both after Arabic normalization.
"""

from __future__ import annotations

import re

_DIACRITICS = re.compile(r"[ً-ْٰـ]")
_ALEF = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"})
_TOKEN = re.compile(r"\w+")


def normalize(text: str) -> str:
    return _DIACRITICS.sub("", text).translate(_ALEF).lower()


# ── Answer side: advice the agent must never give ─────────────────────

ANSWER_FORBIDDEN_TOKENS = frozenset(
    {
        "buy", "sell", "avoid", "hold", "accumulate",
        "اشتر", "اشتري", "اشتروا", "بع", "بيعوا",
        "تجنب", "تجنبوا", "احتفظ", "احتفظوا",
        "ننصح", "انصح", "ينصح", "تنصح",
        "نوصي", "اوصي", "يوصي", "توصي", "توصيه", "توصيتي", "توصياتنا",
    }
)
ANSWER_FORBIDDEN_PHRASES = tuple(
    normalize(p)
    for p in (
        "فرصة شراء", "فرصة للشراء", "فرصة بيع", "فرصة للبيع",
        "نقطة شراء", "نقطة دخول", "نقطة خروج",
        "توقيت الشراء", "توقيت البيع", "وقت الشراء", "وقت البيع",
        "شراء السهم", "بيع السهم", "الاحتفاظ بالسهم",
        "جني الأرباح", "وقف الخسارة", "الدخول في السهم", "الخروج من السهم",
        "should you", "should i", "take profit", "stop loss",
    )
)
# Disclaimers that negate a recommendation are allowed.
_ALLOWED_NEGATIONS = tuple(
    normalize(p)
    for p in (
        "ليست توصية", "ليس توصية", "لا يعد توصية", "لا تعد توصية",
        "لا يمثل توصية", "لا تمثل توصية", "دون توصية", "وليست توصية",
        "not a recommendation", "not investment advice",
    )
)


def find_recommendation_language(text: str) -> list[str]:
    """Return the forbidden terms present in ``text`` (empty when clean)."""
    normalized = normalize(text)
    for allowed in _ALLOWED_NEGATIONS:
        normalized = normalized.replace(allowed, " ")
    hits = [p for p in ANSWER_FORBIDDEN_PHRASES if p in normalized]
    hits.extend(t for t in _TOKEN.findall(normalized) if t in ANSWER_FORBIDDEN_TOKENS)
    return sorted(set(hits))


# ── Question side: parts that ask for a recommendation ────────────────

QUESTION_ADVICE_TOKENS = frozenset(
    {
        "buy", "sell", "hold", "avoid", "recommend", "recommendation",
        "اشتري", "اشتريه", "ابيع", "ابيعه", "احتفظ", "اتجنب",
        "انصح", "تنصح", "تنصحني", "تنصحوني", "توصي", "توصيه", "توصيتك",
        "شراء", "الشراء", "للشراء", "بالشراء", "بيع", "البيع", "للبيع",
        "ادخل", "اخرج",
    }
)
QUESTION_ADVICE_PHRASES = tuple(
    normalize(p)
    for p in ("should i", "worth buying", "يستحق الشراء", "هل يستحق")
)

_SPLIT = re.compile(r"[?؟!.\n؛;]+|\s+(?=وهل\s)|\s+(?=and should\s)", re.IGNORECASE)


def asks_for_recommendation(text: str) -> bool:
    normalized = normalize(text)
    if any(p in normalized for p in QUESTION_ADVICE_PHRASES):
        return True
    return any(t in QUESTION_ADVICE_TOKENS for t in _TOKEN.findall(normalized))


def split_question(question: str) -> tuple[list[str], list[str]]:
    """Split into (descriptive parts, recommendation parts)."""
    descriptive: list[str] = []
    advice: list[str] = []
    for part in _SPLIT.split(question):
        part = part.strip()
        if not part:
            continue
        (advice if asks_for_recommendation(part) else descriptive).append(part)
    return descriptive, advice
