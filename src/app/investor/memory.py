"""Long-term preference memory and re-profiling triggers (Spec Section 7, PLAN-006).

Memory tiers:

1. Working memory - the LangGraph interview state (``state.py`` + checkpointer).
2. Semantic memory - stable preferences in ``learned_preferences``.
3. Episodic memory - reactions to recommendations/alerts, also stored in
   ``learned_preferences`` under ``feedback:*`` keys as rolling counters.

Safety rule (Spec Section 7.2.4): memory never alters the active profile.
Foundational keys are rejected outright, and review triggers only *suggest*
changes that the user must confirm through the HITL profile flow.

The adapter is backed by PostgreSQL today; :class:`PreferenceMemory` lets a
LangMem store replace it later without touching callers.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
import re
from typing import Any, Protocol
from uuid import UUID

from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.investor import repository
from app.investor.models import InvestorProfile, LearnedPreference
from app.investor.schemas import (
    InvestmentHorizon,
    LearnedPreferenceCreate,
    RiskProfile,
)

STALE_PROFILE_DAYS = 180
VOLATILITY_DISMISSAL_THRESHOLD = 3

VOLATILITY_FEEDBACK_KEY = "feedback:too_volatile"
LIFE_EVENT_KEY_PREFIX = "life_event:"

# Keys that map to HITL-gated profile fields. Memory may never write them.
FOUNDATIONAL_PREFERENCE_KEYS = frozenset(
    {
        "risk_profile",
        "risk_capacity",
        "risk_willingness",
        "investment_horizon",
        "investment_goal",
        "investment_experience",
        "liquidity_floor_pct",
        "max_atr_pctl_cap",
    }
)


class FoundationalPreferenceError(ValueError):
    """Raised when memory tries to write a HITL-gated profile field."""


class RecommendationFeedback(StrEnum):
    TOO_VOLATILE = "too_volatile"
    GOOD_TIMING = "good_timing"
    NOT_INTERESTED = "not_interested"


class LifeEventKind(StrEnum):
    HOUSING_PURCHASE = "housing_purchase"
    MARRIAGE = "marriage"
    NEW_CHILD = "new_child"
    JOB_LOSS = "job_loss"
    EDUCATION_EXPENSES = "education_expenses"
    MEDICAL_EXPENSES = "medical_expenses"
    RETIREMENT = "retirement"
    LIQUIDITY_NEED = "liquidity_need"


class ReviewTriggerKind(StrEnum):
    STALE_PROFILE = "stale_profile"
    BEHAVIORAL_DIVERGENCE = "behavioral_divergence"
    LIFE_EVENT = "life_event"


class ReviewTrigger(BaseModel):
    """A suggestion to re-run profiling. Never applied without HITL confirmation."""

    kind: ReviewTriggerKind
    message_ar: str
    suggested_changes: dict[str, str] = Field(default_factory=dict)
    detected_at: datetime


class ProfileReviewStatus(BaseModel):
    """Re-profiling status for the user's active profile."""

    has_active_profile: bool
    profile_version: int | None = None
    needs_review: bool = False
    triggers: list[ReviewTrigger] = Field(default_factory=list)


_LIFE_EVENT_PATTERNS: tuple[tuple[LifeEventKind, tuple[str, ...]], ...] = (
    (LifeEventKind.HOUSING_PURCHASE, ("اشتريت شقة", "شقة جديدة", "أشتري شقة", "اشتري شقة", "bought an apartment", "bought a house")),
    (LifeEventKind.MARRIAGE, ("هتجوز", "سأتزوج", "زواجي", "فرحي", "getting married")),
    (LifeEventKind.NEW_CHILD, ("مولود", "طفل جديد", "new baby")),
    (LifeEventKind.JOB_LOSS, ("فقدت عملي", "فقدت وظيفتي", "اتفصلت", "سبت الشغل", "lost my job")),
    (LifeEventKind.EDUCATION_EXPENSES, ("مصاريف المدارس", "مصاريف الجامعة", "مصاريف الدراسة", "tuition")),
    (LifeEventKind.MEDICAL_EXPENSES, ("عملية جراحية", "مصاريف علاج", "medical bills")),
    (LifeEventKind.RETIREMENT, ("تقاعدت", "على المعاش", "طلعت معاش", "retired")),
    (LifeEventKind.LIQUIDITY_NEED, ("أحتاج للسيولة", "احتاج للسيولة", "محتاج سيولة", "محتاج الفلوس قريب", "need liquidity", "need the money soon")),
)

# Events that shorten how long money can stay invested.
_HORIZON_SHORTENING_EVENTS = frozenset(
    {
        LifeEventKind.HOUSING_PURCHASE,
        LifeEventKind.MARRIAGE,
        LifeEventKind.JOB_LOSS,
        LifeEventKind.EDUCATION_EXPENSES,
        LifeEventKind.MEDICAL_EXPENSES,
        LifeEventKind.LIQUIDITY_NEED,
    }
)

_SHORTER_HORIZON: dict[str, str] = {
    InvestmentHorizon.LONG.value: InvestmentHorizon.MEDIUM.value,
    InvestmentHorizon.MEDIUM.value: InvestmentHorizon.SHORT.value,
}


def detect_life_event(message: str) -> LifeEventKind | None:
    """Detect a major life event in chat text (Spec Section 7.2.3)."""
    lowered = message.strip().lower()
    for kind, phrases in _LIFE_EVENT_PATTERNS:
        if any(phrase in lowered for phrase in phrases):
            return kind
    return None


# --- PII minimization -------------------------------------------------------

_AMOUNT_RE = re.compile(
    r"\d[\d,٬.]*\s*(?:ألف|الف|مليون|k|m|جنيه|ج\.م|egp|\$|usd|دولار)?",
    re.IGNORECASE,
)
_RAW_STATE_KEYS = frozenset({"risk_capacity_raw", "risk_tolerance_raw", "messages"})


def scrub_amounts(text: str) -> str:
    """Replace monetary amounts and other numbers with a placeholder."""
    return _AMOUNT_RE.sub("[redacted]", text)


def _scrub_value(value: Any) -> Any:
    if isinstance(value, str):
        return scrub_amounts(value)
    if isinstance(value, dict):
        return {k: _scrub_value(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_scrub_value(v) for v in value]
    return value


def redact_state_for_logging(values: dict[str, Any]) -> dict[str, Any]:
    """Drop raw financial disclosures and chat text before logging/tracing."""
    return {k: v for k, v in values.items() if k not in _RAW_STATE_KEYS}


# --- Memory adapter --------------------------------------------------------


class PreferenceMemory(Protocol):
    """Storage boundary for semantic/episodic memory (swappable for LangMem)."""

    async def remember(
        self,
        session: AsyncSession,
        user_id: UUID,
        preference: LearnedPreferenceCreate,
    ) -> LearnedPreference: ...

    async def recall(
        self,
        session: AsyncSession,
        user_id: UUID,
        *,
        validated_only: bool = False,
    ) -> list[LearnedPreference]: ...


class PostgresPreferenceMemory:
    """Preference memory backed by the ``learned_preferences`` table."""

    async def remember(
        self,
        session: AsyncSession,
        user_id: UUID,
        preference: LearnedPreferenceCreate,
    ) -> LearnedPreference:
        if preference.preference_key in FOUNDATIONAL_PREFERENCE_KEYS:
            raise FoundationalPreferenceError(
                f"'{preference.preference_key}' can only change via HITL profile confirmation"
            )
        sanitized = preference.model_copy(
            update={"preference_value": _scrub_value(dict(preference.preference_value))}
        )
        return await repository.upsert_learned_preference(session, user_id, sanitized)

    async def recall(
        self,
        session: AsyncSession,
        user_id: UUID,
        *,
        validated_only: bool = False,
    ) -> list[LearnedPreference]:
        return await repository.list_learned_preferences(
            session, user_id, validated_only=validated_only
        )


def _find(preferences: list[LearnedPreference], key: str) -> LearnedPreference | None:
    return next((p for p in preferences if p.preference_key == key), None)


async def record_recommendation_feedback(
    memory: PreferenceMemory,
    session: AsyncSession,
    user_id: UUID,
    feedback: RecommendationFeedback,
    *,
    ticker: str | None = None,
) -> LearnedPreference:
    """Store episodic feedback as a rolling counter keyed by feedback type."""
    key = f"feedback:{feedback.value}"
    existing = _find(await memory.recall(session, user_id), key)
    previous = dict(existing.preference_value) if existing is not None else {}
    count = int(previous.get("count", 0)) + 1
    tickers = list(previous.get("recent_tickers", []))
    if ticker:
        tickers = ([ticker.strip().upper()] + [t for t in tickers if t != ticker.strip().upper()])[:10]
    return await memory.remember(
        session,
        user_id,
        LearnedPreferenceCreate(
            preference_key=key,
            preference_value={"count": count, "recent_tickers": tickers},
            confidence_score=min(1.0, 0.3 + 0.15 * count),
            source_event="recommendation_feedback",
        ),
    )


async def record_life_event(
    memory: PreferenceMemory,
    session: AsyncSession,
    user_id: UUID,
    event: LifeEventKind,
) -> LearnedPreference:
    """Store a detected life event (unvalidated) for the review-status check."""
    return await memory.remember(
        session,
        user_id,
        LearnedPreferenceCreate(
            preference_key=f"{LIFE_EVENT_KEY_PREFIX}{event.value}",
            preference_value={"event": event.value},
            confidence_score=0.6,
            source_event="interview_chat",
        ),
    )


def evaluate_review_triggers(
    profile: InvestorProfile,
    preferences: list[LearnedPreference],
    *,
    now: datetime | None = None,
) -> list[ReviewTrigger]:
    """Return re-profiling suggestions for an active profile (Spec Section 7.2).

    Pure function: it reads memory and the profile but never modifies either.
    """
    current = now or datetime.now(UTC)
    triggers: list[ReviewTrigger] = []

    last_reviewed = profile.last_reviewed_at or profile.confirmed_at
    if last_reviewed is not None and current - last_reviewed >= timedelta(days=STALE_PROFILE_DAYS):
        triggers.append(
            ReviewTrigger(
                kind=ReviewTriggerKind.STALE_PROFILE,
                message_ar=(
                    f"مرّ أكثر من {STALE_PROFILE_DAYS} يوماً على آخر مراجعة لملفك الاستثماري. "
                    "نقترح مراجعة سريعة للتأكد من أنه ما زال يعبر عن وضعك الحالي."
                ),
                detected_at=current,
            )
        )

    volatility = _find(preferences, VOLATILITY_FEEDBACK_KEY)
    if (
        profile.risk_profile == RiskProfile.AGGRESSIVE.value
        and volatility is not None
        and int(volatility.preference_value.get("count", 0)) >= VOLATILITY_DISMISSAL_THRESHOLD
    ):
        triggers.append(
            ReviewTrigger(
                kind=ReviewTriggerKind.BEHAVIORAL_DIVERGENCE,
                message_ar=(
                    "لاحظنا أنك رفضت عدة توصيات بسبب التذبذب المرتفع رغم أن ملفك مصنف "
                    "كمرتفع المخاطرة. هل تود مراجعة مستوى المخاطرة المناسب لك؟"
                ),
                suggested_changes={"risk_profile": RiskProfile.MODERATE.value},
                detected_at=current,
            )
        )

    for pref in preferences:
        if not pref.preference_key.startswith(LIFE_EVENT_KEY_PREFIX) or pref.user_validated:
            continue
        if profile.confirmed_at is not None and pref.updated_at < profile.confirmed_at:
            continue  # Already reflected in a later confirmed profile.
        try:
            event = LifeEventKind(pref.preference_key.removeprefix(LIFE_EVENT_KEY_PREFIX))
        except ValueError:
            continue
        suggested: dict[str, str] = {}
        shorter = _SHORTER_HORIZON.get(profile.investment_horizon)
        if event in _HORIZON_SHORTENING_EVENTS and shorter is not None:
            suggested["investment_horizon"] = shorter
        triggers.append(
            ReviewTrigger(
                kind=ReviewTriggerKind.LIFE_EVENT,
                message_ar=(
                    "ذكرت تغيراً مهماً في ظروفك قد يؤثر على احتياجك للسيولة. "
                    "نقترح مراجعة الأفق الزمني لاستثماراتك وتأكيد الملف من جديد."
                ),
                suggested_changes=suggested,
                detected_at=current,
            )
        )

    return triggers
