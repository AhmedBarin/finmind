"""Tests for preference memory, re-profiling triggers, and PII minimization."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any
from uuid import uuid4

import pytest

from app.investor import repository
from app.investor.memory import (
    FoundationalPreferenceError,
    LifeEventKind,
    PostgresPreferenceMemory,
    RecommendationFeedback,
    ReviewTriggerKind,
    detect_life_event,
    evaluate_review_triggers,
    record_recommendation_feedback,
    redact_state_for_logging,
    scrub_amounts,
)
from app.investor.models import InvestorProfile, LearnedPreference
from app.investor.schemas import LearnedPreferenceCreate

NOW = datetime(2026, 11, 13, tzinfo=UTC)


def _profile(**overrides: Any) -> InvestorProfile:
    values: dict[str, Any] = {
        "id": uuid4(),
        "user_id": uuid4(),
        "risk_profile": "moderate",
        "investment_horizon": "long",
        "investment_goal": "growth",
        "investment_experience": "intermediate",
        "liquidity_floor_pct": Decimal("70"),
        "max_atr_pctl_cap": Decimal("75"),
        "excluded_sectors": [],
        "excluded_tickers": [],
        "preferred_sectors": [],
        "is_active": True,
        "profile_version": 1,
        "confirmed_at": NOW - timedelta(days=10),
        "last_reviewed_at": NOW - timedelta(days=10),
    }
    values.update(overrides)
    return InvestorProfile(**values)


def _pref(key: str, value: dict, *, updated_at: datetime = NOW, validated: bool = False) -> LearnedPreference:
    return LearnedPreference(
        id=uuid4(),
        user_id=uuid4(),
        preference_key=key,
        preference_value=value,
        confidence_score=Decimal("0.6"),
        source_event="test",
        user_validated=validated,
        created_at=updated_at,
        updated_at=updated_at,
    )


# --- Life events -------------------------------------------------------------


@pytest.mark.parametrize(
    ("message", "expected"),
    [
        ("لقد اشتريت شقة جديدة وأحتاج للسيولة قريباً", LifeEventKind.HOUSING_PURCHASE),
        ("فقدت وظيفتي الشهر الماضي", LifeEventKind.JOB_LOSS),
        ("محتاج سيولة للمصاريف", LifeEventKind.LIQUIDITY_NEED),
        ("هدفي تنمية رأس المال", None),
    ],
)
def test_detect_life_event(message: str, expected: LifeEventKind | None) -> None:
    assert detect_life_event(message) == expected


# --- Review triggers ----------------------------------------------------------


def test_fresh_profile_has_no_triggers() -> None:
    assert evaluate_review_triggers(_profile(), [], now=NOW) == []


def test_stale_profile_after_180_days() -> None:
    profile = _profile(last_reviewed_at=NOW - timedelta(days=181))
    [trigger] = evaluate_review_triggers(profile, [], now=NOW)
    assert trigger.kind is ReviewTriggerKind.STALE_PROFILE


def test_volatility_dismissals_flag_aggressive_profile_only() -> None:
    prefs = [_pref("feedback:too_volatile", {"count": 3})]
    [trigger] = evaluate_review_triggers(_profile(risk_profile="aggressive"), prefs, now=NOW)
    assert trigger.kind is ReviewTriggerKind.BEHAVIORAL_DIVERGENCE
    assert trigger.suggested_changes == {"risk_profile": "moderate"}

    assert evaluate_review_triggers(_profile(risk_profile="moderate"), prefs, now=NOW) == []
    assert (
        evaluate_review_triggers(
            _profile(risk_profile="aggressive"),
            [_pref("feedback:too_volatile", {"count": 2})],
            now=NOW,
        )
        == []
    )


def test_life_event_suggests_shorter_horizon() -> None:
    prefs = [_pref("life_event:housing_purchase", {"event": "housing_purchase"})]
    [trigger] = evaluate_review_triggers(_profile(investment_horizon="long"), prefs, now=NOW)
    assert trigger.kind is ReviewTriggerKind.LIFE_EVENT
    assert trigger.suggested_changes == {"investment_horizon": "medium"}


def test_life_event_before_latest_confirmation_is_ignored() -> None:
    prefs = [
        _pref(
            "life_event:housing_purchase",
            {"event": "housing_purchase"},
            updated_at=NOW - timedelta(days=30),
        )
    ]
    assert evaluate_review_triggers(_profile(), prefs, now=NOW) == []


def test_triggers_never_modify_the_profile() -> None:
    profile = _profile(risk_profile="aggressive", last_reviewed_at=NOW - timedelta(days=400))
    before = (profile.risk_profile, profile.investment_horizon, profile.profile_version)
    evaluate_review_triggers(
        profile,
        [
            _pref("feedback:too_volatile", {"count": 9}),
            _pref("life_event:job_loss", {"event": "job_loss"}),
        ],
        now=NOW,
    )
    assert (profile.risk_profile, profile.investment_horizon, profile.profile_version) == before


# --- Memory adapter -------------------------------------------------------------


@pytest.mark.asyncio
async def test_memory_rejects_foundational_keys() -> None:
    memory = PostgresPreferenceMemory()
    with pytest.raises(FoundationalPreferenceError):
        await memory.remember(
            None,  # type: ignore[arg-type]
            uuid4(),
            LearnedPreferenceCreate(
                preference_key="risk_profile",
                preference_value={"value": "aggressive"},
                confidence_score=0.9,
                source_event="chat",
            ),
        )


@pytest.mark.asyncio
async def test_memory_scrubs_amounts_before_storage(monkeypatch: pytest.MonkeyPatch) -> None:
    stored: list[LearnedPreferenceCreate] = []

    async def fake_upsert(session, user_id, preference):
        stored.append(preference)
        return preference

    monkeypatch.setattr(repository, "upsert_learned_preference", fake_upsert)
    await PostgresPreferenceMemory().remember(
        None,  # type: ignore[arg-type]
        uuid4(),
        LearnedPreferenceCreate(
            preference_key="note",
            preference_value={"text": "مرتبي 25,000 جنيه وعندي ديون 300 ألف"},
            confidence_score=0.5,
            source_event="chat",
        ),
    )
    text = stored[0].preference_value["text"]
    assert "25,000" not in text and "300" not in text
    assert "[redacted]" in text


@pytest.mark.asyncio
async def test_feedback_counter_increments() -> None:
    class InMemory:
        def __init__(self) -> None:
            self.rows: dict[str, LearnedPreference] = {}

        async def remember(self, session, user_id, pref):
            row = _pref(pref.preference_key, dict(pref.preference_value))
            self.rows[pref.preference_key] = row
            return row

        async def recall(self, session, user_id, *, validated_only=False):
            return list(self.rows.values())

    memory = InMemory()
    user_id = uuid4()
    for ticker in ("comi", "etel", "comi"):
        row = await record_recommendation_feedback(
            memory, None, user_id, RecommendationFeedback.TOO_VOLATILE, ticker=ticker  # type: ignore[arg-type]
        )
    assert row.preference_key == "feedback:too_volatile"
    assert row.preference_value == {"count": 3, "recent_tickers": ["COMI", "ETEL"]}


# --- PII ---------------------------------------------------------------------------


def test_redact_state_drops_raw_disclosures() -> None:
    redacted = redact_state_for_logging(
        {
            "risk_capacity_raw": "عندي ديون 300 ألف",
            "risk_tolerance_raw": "x",
            "messages": ["..."],
            "risk_capacity": "low",
        }
    )
    assert redacted == {"risk_capacity": "low"}


def test_scrub_amounts() -> None:
    assert scrub_amounts("مرتبي 15000 جنيه") == "مرتبي [redacted]"
