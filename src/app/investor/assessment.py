"""Deterministic risk assessment, coherence validation, and safety guardrails."""

from __future__ import annotations

from dataclasses import dataclass
import re

from app.investor.schemas import (
    InvestmentExperience,
    InvestmentGoal,
    InvestmentHorizon,
    RiskCapacity,
    RiskProfile,
    RiskWillingness,
)

# Spec Section 6.1: Matrix of Financial Capacity x Psychological Willingness.
# Low capacity caps Aggressive willingness at Moderate (safety guard).
RISK_MATRIX: dict[tuple[RiskCapacity, RiskWillingness], RiskProfile] = {
    (RiskCapacity.LOW, RiskWillingness.CONSERVATIVE): RiskProfile.CONSERVATIVE,
    (RiskCapacity.LOW, RiskWillingness.MODERATE): RiskProfile.CONSERVATIVE,
    (RiskCapacity.LOW, RiskWillingness.AGGRESSIVE): RiskProfile.MODERATE,
    (RiskCapacity.MEDIUM, RiskWillingness.CONSERVATIVE): RiskProfile.CONSERVATIVE,
    (RiskCapacity.MEDIUM, RiskWillingness.MODERATE): RiskProfile.MODERATE,
    (RiskCapacity.MEDIUM, RiskWillingness.AGGRESSIVE): RiskProfile.AGGRESSIVE,
    (RiskCapacity.HIGH, RiskWillingness.CONSERVATIVE): RiskProfile.MODERATE,
    (RiskCapacity.HIGH, RiskWillingness.MODERATE): RiskProfile.AGGRESSIVE,
    (RiskCapacity.HIGH, RiskWillingness.AGGRESSIVE): RiskProfile.AGGRESSIVE,
}

INTERVIEW_DIMENSION_ORDER: tuple[str, ...] = (
    "investment_goal",
    "investment_horizon",
    "risk_profile",
    "investment_experience",
)


@dataclass(frozen=True)
class RiskAssessmentResult:
    """Output of deterministic capacity-vs-willingness gating."""

    risk_profile: RiskProfile
    safety_cap_applied: bool
    cap_reason_ar: str | None = None


@dataclass(frozen=True)
class CoherenceValidationResult:
    """Result of deterministic profile validation for an interview turn."""

    derived_risk_profile: RiskProfile | None
    safety_cap_applied: bool
    cap_reason_ar: str | None
    conflicts: tuple[str, ...]
    clarification_prompt_ar: str | None
    missing_dimensions: tuple[str, ...]

    @property
    def is_coherent(self) -> bool:
        return not self.conflicts

    @property
    def is_complete(self) -> bool:
        return self.is_coherent and not self.missing_dimensions


def assess_risk_profile(
    capacity: RiskCapacity,
    willingness: RiskWillingness,
) -> RiskAssessmentResult:
    """Deterministically combine financial capacity and psychological tolerance."""
    derived = RISK_MATRIX[(capacity, willingness)]
    safety_cap_applied = (
        capacity is RiskCapacity.LOW and willingness is RiskWillingness.AGGRESSIVE
    )
    cap_reason = (
        "نظراً لأن السيولة المتاحة مرتبطة بالتزامات قريبة أو مدخرات طوارئ، "
        "تم وضع حد أقصى لمستوى المخاطرة عند المستوى المعتدل (Moderate) لحماية رأس مالك."
        if safety_cap_applied
        else None
    )
    return RiskAssessmentResult(
        risk_profile=derived,
        safety_cap_applied=safety_cap_applied,
        cap_reason_ar=cap_reason,
    )


def compute_missing_dimensions(
    *,
    investment_goal: InvestmentGoal | str | None,
    investment_horizon: InvestmentHorizon | str | None,
    derived_risk_profile: RiskProfile | str | None,
    investment_experience: InvestmentExperience | str | None,
) -> tuple[str, ...]:
    """Return missing profiling dimensions in the Spec Section 5.3 order."""
    slot_values = {
        "investment_goal": investment_goal,
        "investment_horizon": investment_horizon,
        "risk_profile": derived_risk_profile,
        "investment_experience": investment_experience,
    }
    return tuple(dim for dim in INTERVIEW_DIMENSION_ORDER if not slot_values[dim])


def _coerce_enum(enum_cls: type, value: object) -> object:
    if value is None or isinstance(value, enum_cls):
        return value
    return enum_cls(str(value))


def validate_coherence(
    *,
    investment_goal: InvestmentGoal | str | None,
    investment_horizon: InvestmentHorizon | str | None,
    risk_capacity: RiskCapacity | str | None,
    risk_willingness: RiskWillingness | str | None,
    derived_risk_profile: RiskProfile | str | None,
    investment_experience: InvestmentExperience | str | None,
    zero_loss_high_return_claim: bool = False,
) -> CoherenceValidationResult:
    """Validate deterministic risk gating and detect contradictory user answers."""
    goal = _coerce_enum(InvestmentGoal, investment_goal)
    horizon = _coerce_enum(InvestmentHorizon, investment_horizon)
    capacity = _coerce_enum(RiskCapacity, risk_capacity)
    willingness = _coerce_enum(RiskWillingness, risk_willingness)
    experience = _coerce_enum(InvestmentExperience, investment_experience)
    resolved_profile = _coerce_enum(RiskProfile, derived_risk_profile)

    safety_cap_applied = False
    cap_reason: str | None = None
    if capacity is not None and willingness is not None:
        assessed = assess_risk_profile(capacity, willingness)  # type: ignore[arg-type]
        resolved_profile = assessed.risk_profile
        safety_cap_applied = assessed.safety_cap_applied
        cap_reason = assessed.cap_reason_ar

    conflicts: list[str] = []
    clarifications: list[str] = []

    if zero_loss_high_return_claim:
        conflicts.append("zero_risk_high_return_contradiction")
        clarifications.append(
            "في البورصة المصرية، العائد المرتفع السريع يرتبط دائماً بمخاطرة وتقلبات سعرية "
            "واحتمال خسارة جزء من رأس المال. هل نركز على حماية رأس المال بعوائد هادئة، "
            "أم تقبل تقلبات أكبر بهدف النمو السريع؟"
        )

    if (
        goal is InvestmentGoal.CAPITAL_PRESERVATION
        and willingness is RiskWillingness.AGGRESSIVE
    ):
        conflicts.append("goal_vs_willingness_contradiction")
        clarifications.append(
            "ذكرت أن هدفك الأساسي هو الحفاظ على رأس المال، وفي الوقت نفسه عبّرت عن تقبل "
            "مخاطرة مرتفعة. أيهما يعبر بدقة أكبر عن أولويتك الحالية؟"
        )

    if (
        goal is InvestmentGoal.SPECULATION
        and capacity is RiskCapacity.LOW
    ):
        conflicts.append("speculation_with_low_capacity")
        clarifications.append(
            "المضاربة السريعة لا تناسب الأموال المخصصة للطوارئ أو الالتزامات القريبة. "
            "هل تفضل تعديل الهدف إلى الحفاظ على رأس المال أو النمو المتوازن؟"
        )

    if (
        goal is InvestmentGoal.CAPITAL_PRESERVATION
        and horizon is InvestmentHorizon.SHORT
        and willingness is RiskWillingness.AGGRESSIVE
    ):
        conflicts.append("short_horizon_preservation_mismatch")

    missing = compute_missing_dimensions(
        investment_goal=goal,
        investment_horizon=horizon,
        derived_risk_profile=resolved_profile,
        investment_experience=experience,
    )

    return CoherenceValidationResult(
        derived_risk_profile=resolved_profile,  # type: ignore[arg-type]
        safety_cap_applied=safety_cap_applied,
        cap_reason_ar=cap_reason,
        conflicts=tuple(conflicts),
        clarification_prompt_ar=" ".join(clarifications) if clarifications else None,
        missing_dimensions=missing,
    )


_OFF_TOPIC_TRADE_TRIGGERS = (
    "أشتري",
    "اشتري",
    "أبيع",
    "ابيع",
    "توصية",
    "توصيات",
    "رشحلي سهم",
    "سهم إيه",
    "should i buy",
    "should i sell",
    "recommend a stock",
    "stock pick",
)


# Match whole words only, so past-tense life events such as "اشتريت شقة"
# ("I bought an apartment") are not mistaken for buy/sell requests. A single
# optional Arabic proclitic (و/ف/ه/ال) is allowed before the trigger.
_OFF_TOPIC_TRADE_RE = re.compile(
    r"(?<!\w)(?:و|ف|ه|ال)?(?:"
    + "|".join(re.escape(trigger) for trigger in _OFF_TOPIC_TRADE_TRIGGERS)
    + r")(?!\w)"
)


def is_off_topic_stock_query(message: str) -> bool:
    """Detect direct buy/sell recommendation queries during profiling (Golden Rule 3)."""
    lowered = message.strip().lower()
    return _OFF_TOPIC_TRADE_RE.search(lowered) is not None



_PROMPT_INJECTION_RE = re.compile(
    r"(ignore\s+(?:all\s+|the\s+)?(?:previous|above|prior)\s+(?:instructions|rules|prompts?)"
    r"|disregard\s+(?:all\s+|the\s+)?(?:previous|above|prior)"
    r"|system\s*prompt|you\s+are\s+now|act\s+as\s+(?:a|an)\s"
    r"|developer\s+mode|jailbreak"
    r"|تجاهل\s+(?:كل\s+|جميع\s+)?(?:التعليمات|الأوامر|القواعد)"
    r"|انس(?:ى)?\s+(?:كل\s+)?(?:التعليمات|الأوامر|القواعد)"
    r"|أنت\s+الآن|انت\s+الان|تعليمات\s+النظام)",
    re.IGNORECASE,
)


def is_prompt_injection_attempt(message: str) -> bool:
    """Detect common Arabic/English prompt-injection phrasing (Spec Section 11)."""
    return _PROMPT_INJECTION_RE.search(message) is not None
