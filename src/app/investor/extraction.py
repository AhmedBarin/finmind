"""Deterministic Arabic/English slot extraction for the investor interview.

The rule-based extractor is the always-available baseline: it runs in tests,
when no LLM is configured, and as the fallback when the LLM extractor fails.
"""

from __future__ import annotations

from dataclasses import dataclass, field, fields
import re
from typing import Protocol

from app.investor.schemas import (
    InvestmentExperience,
    InvestmentGoal,
    InvestmentHorizon,
    RiskCapacity,
    RiskWillingness,
)
from app.investor.state import InvestorAgentState


@dataclass
class ExtractionPatch:
    """Structured slots extracted from a single user message."""

    investment_goal: InvestmentGoal | None = None
    investment_horizon: InvestmentHorizon | None = None
    risk_capacity: RiskCapacity | None = None
    risk_willingness: RiskWillingness | None = None
    risk_capacity_raw: str | None = None
    risk_tolerance_raw: str | None = None
    investment_experience: InvestmentExperience | None = None
    excluded_sectors: list[str] = field(default_factory=list)
    excluded_tickers: list[str] = field(default_factory=list)
    preferred_sectors: list[str] = field(default_factory=list)
    zero_loss_high_return_claim: bool = False

    def is_empty(self) -> bool:
        """True when nothing usable was extracted from the message."""
        return not any(getattr(self, f.name) for f in fields(self))


class InterviewTurnExtractor(Protocol):
    """Abstraction allowing LLM extractors to replace deterministic rules."""

    def extract(self, message: str, state: InvestorAgentState) -> ExtractionPatch:
        ...


# Canonical EGX sector names (English) and their Arabic/English surface forms.
SECTOR_KEYWORDS: dict[str, tuple[str, ...]] = {
    "Banks": ("البنوك", "بنوك", "القطاع المصرفي", "المصارف", "banks", "banking"),
    "Real Estate": ("العقارات", "العقاري", "عقارات", "real estate"),
    "Tobacco": ("التبغ", "الدخان", "السجائر", "tobacco"),
    "Telecommunications": ("الاتصالات", "اتصالات", "telecom"),
    "Technology": ("التكنولوجيا", "تكنولوجيا", "التقنية", "technology", "tech"),
    "Food & Beverages": ("الأغذية", "الاغذية", "المشروبات", "food", "beverage"),
    "Healthcare & Pharmaceuticals": ("الرعاية الصحية", "الأدوية", "الادوية", "healthcare", "pharma"),
    "Basic Resources": ("الموارد الأساسية", "الموارد الاساسية", "الحديد", "الصلب", "steel", "basic resources"),
    "Chemicals & Fertilizers": ("الكيماويات", "الأسمدة", "الاسمدة", "chemicals", "fertilizer"),
    "Construction & Building Materials": ("المقاولات", "مواد البناء", "الأسمنت", "الاسمنت", "construction", "cement"),
    "Industrial Goods": ("الصناعات", "السلع الصناعية", "industrial"),
    "Energy": ("الطاقة", "البترول", "الغاز", "energy", "oil", "gas"),
    "Tourism & Leisure": ("السياحة", "الفنادق", "tourism", "hotels"),
    "Non-Bank Financial Services": ("الخدمات المالية غير المصرفية", "التمويل", "الوساطة", "non-bank", "brokerage"),
    "Textiles": ("المنسوجات", "الغزل والنسيج", "textiles"),
    "Gambling & Alcohol": ("القمار", "الخمور", "الكحول", "gambling", "alcohol"),
}

# Well-known EGX companies referred to by name instead of ticker.
COMPANY_TICKERS: dict[str, str] = {
    "التجاري الدولي": "COMI",
    "المصرية للاتصالات": "ETEL",
    "الشرقية للدخان": "EAST",
    "ايسترن كومباني": "EAST",
    "هيرميس": "HRHO",
    "السويدي": "SWDY",
    "طلعت مصطفى": "TMGH",
    "حديد عز": "ESRS",
    "عز للصلب": "ESRS",
    "فوري": "FWRY",
    "أبوقير للأسمدة": "ABUK",
    "ابوقير للاسمدة": "ABUK",
}

_TICKER_STOPWORDS = frozenset(
    {"EGX", "ATR", "RSI", "ETF", "USD", "EGP", "CEO", "IPO", "MACD", "EMA", "SMA", "OK"}
)
_TICKER_RE = re.compile(r"(?<![A-Za-z0-9])([A-Z]{3,5})(?:\.CA)?(?![A-Za-z0-9])")

_EXCLUSION_MARKERS: tuple[str, ...] = (
    "استبعد", "استبعاد", "لا أريد", "لا اريد", "مش عايز", "مش عاوز", "ماعدا", "ما عدا",
    "عدا", "بعيد عن", "بعيدا عن", "بعيداً عن", "تجنب", "أتجنب", "اتجنب", "لا أستثمر",
    "لا استثمر", "بلاش", "exclude", "avoid", "except", "not interested",
)
_PREFERENCE_MARKERS: tuple[str, ...] = (
    "أفضل", "افضل", "تفضيل", "أحب", "احب", "مهتم", "أركز", "اركز", "prefer", "interested", "focus",
)
_CLAUSE_SPLIT_RE = re.compile(r"[.,،؛;!?\n]|\s+لكن\s+|\s+بس\s+|\s+but\s+")


def _clause_intent(clause: str) -> str | None:
    """Return "exclude", "prefer", or None for a clause mentioning a sector/ticker."""
    lowered = clause.lower()
    if any(marker in lowered for marker in _EXCLUSION_MARKERS):
        return "exclude"
    if any(marker in lowered for marker in _PREFERENCE_MARKERS):
        return "prefer"
    return None


def extract_sector_and_ticker_constraints(
    text: str,
) -> tuple[list[str], list[str], list[str]]:
    """Return (excluded_sectors, excluded_tickers, preferred_sectors) from free text.

    Sectors and tickers are only captured when their clause carries an explicit
    exclusion or preference marker, so neutral mentions are ignored.
    """
    excluded_sectors: list[str] = []
    excluded_tickers: list[str] = []
    preferred_sectors: list[str] = []

    for clause in _CLAUSE_SPLIT_RE.split(text):
        if not clause.strip():
            continue
        intent = _clause_intent(clause)
        if intent is None:
            continue
        lowered = clause.lower()

        for sector, keywords in SECTOR_KEYWORDS.items():
            if any(kw in lowered for kw in keywords):
                target = excluded_sectors if intent == "exclude" else preferred_sectors
                if sector not in target:
                    target.append(sector)

        if intent != "exclude":
            continue
        for match in _TICKER_RE.finditer(clause):
            ticker = match.group(1)
            if ticker not in _TICKER_STOPWORDS and ticker not in excluded_tickers:
                excluded_tickers.append(ticker)
        for name, ticker in COMPANY_TICKERS.items():
            if name in clause and ticker not in excluded_tickers:
                excluded_tickers.append(ticker)

    return excluded_sectors, excluded_tickers, preferred_sectors


class RuleBasedArabicExtractor:
    """Deterministic Arabic/English keyword slot extractor."""

    _GOAL_RULES: tuple[tuple[tuple[str, ...], InvestmentGoal], ...] = (
        (("مضاربة", "مضارب", "سريعة", "speculat"), InvestmentGoal.SPECULATION),
        (("توزيعات", "دخل", "أرباح دورية", "income", "dividend"), InvestmentGoal.INCOME),
        (("حماية", "الحفاظ", "مدخرات", "تحوط", "preservation", "preserve"), InvestmentGoal.CAPITAL_PRESERVATION),
        (("تنمية", "نمو", "growth"), InvestmentGoal.GROWTH),
    )

    _HORIZON_RULES: tuple[tuple[tuple[str, ...], InvestmentHorizon], ...] = (
        (("قصير الأجل", "قصير", "أسبوع", "أسبوعين", "أسابيع", "أيام", "يومي", "short"), InvestmentHorizon.SHORT),
        (("متوسط الأجل", "أشهر", "شهور", "1 إلى 6", "medium"), InvestmentHorizon.MEDIUM),
        (("طويل الأجل", "طويل", "عام", "سنة", "سنوات", "أكثر من 6", "long"), InvestmentHorizon.LONG),
    )

    _CAPACITY_RULES: tuple[tuple[tuple[str, ...], RiskCapacity], ...] = (
        (("طوارئ", "التزامات", "ديون", "قرض", "محتاجها قريب", "مرتبطة", "low capacity"), RiskCapacity.LOW),
        (("فائض كبير", "قدرة عالية", "سيولة مرتفعة", "لا أحتاجها", "high capacity"), RiskCapacity.HIGH),
        (("فائضة", "فائض", "فايضة", "فايض", "مستقرة", "مش محتاجها", "قدرة متوسطة", "medium capacity"), RiskCapacity.MEDIUM),
    )

    _WILLINGNESS_RULES: tuple[tuple[tuple[str, ...], RiskWillingness], ...] = (
        (("متحفظ", "لا أتحمل", "أرفض الخسارة", "أقل مخاطرة", "conservative"), RiskWillingness.CONSERVATIVE),
        (("أتحمل التذبذب", "مخاطرة عالية", "أقبل المخاطرة", "مخاطرة مرتفعة", "هجومي", "مش هتفرق معايا", "أشتري أكتر", "aggressive"), RiskWillingness.AGGRESSIVE),
        (("معتدل", "متوازن", "تقلبات معقولة", "مخاطرة متوسطة", "moderate"), RiskWillingness.MODERATE),
    )

    _EXPERIENCE_RULES: tuple[tuple[tuple[str, ...], InvestmentExperience], ...] = (
        (("خبرة متقدمة", "متقدم", "خبرة طويلة", "أكثر من 3 سنوات", "محترف", "advanced"), InvestmentExperience.ADVANCED),
        (("خبرة متوسطة", "خبرتي متوسطة", "سنة إلى 3", "intermediate"), InvestmentExperience.INTERMEDIATE),
        (("مبتدئ", "جديد", "أول مرة", "أقل من سنة", "beginner"), InvestmentExperience.BEGINNER),
    )

    _NO_RISK_HIGH_RETURN_RE = re.compile(
        r"(بدون\s*(?:أي\s*)?مخاطر(?:ة)?|بلا\s*خسار(?:ة)?|zero\s*risk|no\s*risk)"
    )
    _HIGH_RETURN_RE = re.compile(r"(ربح\s*سريع|أرباح\s*(?:عالية|سريعة)|30%|مضاربة|high\s*return)")

    def extract(self, message: str, state: InvestorAgentState) -> ExtractionPatch:
        text = message.strip()
        lowered = text.lower()
        current_dim = state.get("current_dimension")
        patch = ExtractionPatch()

        for keywords, goal in self._GOAL_RULES:
            if any(kw in lowered for kw in keywords):
                patch.investment_goal = goal
                break

        for keywords, horizon in self._HORIZON_RULES:
            if any(kw in lowered for kw in keywords):
                patch.investment_horizon = horizon
                break
        if patch.investment_horizon is None and current_dim == "investment_horizon" and "متوسط" in lowered:
            patch.investment_horizon = InvestmentHorizon.MEDIUM

        for keywords, capacity in self._CAPACITY_RULES:
            if any(kw in lowered for kw in keywords):
                patch.risk_capacity = capacity
                patch.risk_capacity_raw = text
                break

        for keywords, willingness in self._WILLINGNESS_RULES:
            if any(kw in lowered for kw in keywords):
                patch.risk_willingness = willingness
                patch.risk_tolerance_raw = text
                break

        for keywords, experience in self._EXPERIENCE_RULES:
            if any(kw in lowered for kw in keywords):
                patch.investment_experience = experience
                break
        if patch.investment_experience is None and current_dim == "investment_experience" and "متوسط" in lowered:
            patch.investment_experience = InvestmentExperience.INTERMEDIATE

        if self._NO_RISK_HIGH_RETURN_RE.search(lowered) and self._HIGH_RETURN_RE.search(lowered):
            patch.zero_loss_high_return_claim = True
            patch.risk_willingness = patch.risk_willingness or RiskWillingness.AGGRESSIVE
            patch.risk_tolerance_raw = text

        excluded_sectors, excluded_tickers, preferred_sectors = (
            extract_sector_and_ticker_constraints(text)
        )
        patch.excluded_sectors = excluded_sectors
        patch.excluded_tickers = excluded_tickers
        patch.preferred_sectors = preferred_sectors
        return patch
