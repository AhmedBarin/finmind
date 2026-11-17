from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import pytest
from pydantic import ValidationError

import app.recommendation.inputs as recommendation_inputs
from app.investor.schemas import (
    InvestmentExperience,
    InvestmentGoal,
    InvestmentHorizon,
    InvestorProfilePayload,
    RiskProfile,
)
from app.recommendation.inputs import load_recommendation_inputs
from app.recommendation.schemas import (
    ConfidenceLevel,
    RecommendationDecision,
    RecommendationEvaluateRequest,
    RecommendationInputs,
    RecommendationResult,
    UserFit,
)


def _profile(user_id=None) -> InvestorProfilePayload:
    return InvestorProfilePayload(
        user_id=user_id or uuid4(),
        risk_profile=RiskProfile.MODERATE,
        investment_horizon=InvestmentHorizon.MEDIUM,
        investment_goal=InvestmentGoal.GROWTH,
        investment_experience=InvestmentExperience.INTERMEDIATE,
        liquidity_floor_pct=70,
        max_atr_pctl_cap=75,
        profile_version=2,
        is_active=True,
        confirmed_at=datetime(2026, 11, 14, tzinfo=UTC),
    )


def _snapshot(**overrides: object) -> SimpleNamespace:
    values: dict[str, object] = {
        "id": uuid4(),
        "ticker": "COMI.CA",
        "date": date(2026, 11, 12),
        "calculated_at": datetime(2026, 11, 12, 15, 30, tzinfo=UTC),
        "config_version": "technical-v1",
        "input_hash": "a" * 64,
        "data_quality_status": "valid",
        "rsi": 54.2,
        "sma_20": 51.0,
        "sma_50": 48.0,
        "atr": 2.5,
        "setup_score": 67.0,
        "regime": "trending",
        "risk_label": "medium",
        "input_data": {"history_session_count": 260},
        "indicators": {"rsi14": 54.2},
        "scores": {"setup_score": {"score": 67.0}},
        "quality_flags": [],
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def test_evaluate_request_normalizes_ticker() -> None:
    request = RecommendationEvaluateRequest(ticker="  comi.ca ")

    assert request.ticker == "COMI.CA"


def test_inputs_require_matching_user_and_valid_matching_snapshot() -> None:
    user_id = uuid4()
    profile = _profile(user_id)
    snapshot = _snapshot()

    inputs = RecommendationInputs(
        user_id=user_id,
        ticker="comi.ca",
        profile=profile,
        snapshot=snapshot,
    )
    assert inputs.ticker == "COMI.CA"

    with pytest.raises(ValidationError, match="different user"):
        RecommendationInputs(
            user_id=uuid4(),
            ticker="COMI.CA",
            profile=profile,
            snapshot=None,
        )

    with pytest.raises(ValidationError, match="must be valid"):
        RecommendationInputs(
            user_id=user_id,
            ticker="COMI.CA",
            profile=None,
            snapshot=_snapshot(data_quality_status="stale"),
        )

    with pytest.raises(ValidationError, match="does not match"):
        RecommendationInputs(
            user_id=user_id,
            ticker="COMI.CA",
            profile=None,
            snapshot=_snapshot(ticker="SWDY.CA"),
        )


def test_recommendation_result_matches_downstream_contract() -> None:
    result = RecommendationResult(
        ticker="COMI.CA",
        trading_date=date(2026, 11, 12),
        snapshot_id=uuid4(),
        config_version="recommendation-v1",
        decision=RecommendationDecision.WATCH,
        watch_reasons=["momentum"],
        confidence=ConfidenceLevel.MEDIUM,
        families={"trend": {"score": 72, "min_required": 65, "passed": True}},
        user_fit=UserFit(
            risk_profile="moderate",
            horizon="medium",
            goal="growth",
        ),
        data_quality={"price_status": "valid", "last_price_date": "2026-11-12"},
    )

    payload = result.model_dump(mode="json")
    assert payload["decision"] == "WATCH"
    assert payload["confidence"] == "Medium"
    assert payload["families"]["trend"]["score"] == 72
    assert "news" not in payload


@pytest.mark.asyncio
async def test_input_adapter_reads_profile_and_newest_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    profile = _profile(user_id)
    snapshot = _snapshot()
    calls: list[tuple[str, object]] = []

    async def fake_profile(_session, requested_user_id):
        calls.append(("profile", requested_user_id))
        return profile

    async def fake_snapshot(_session, requested_ticker):
        calls.append(("snapshot", requested_ticker))
        return snapshot

    class FakeSession:
        async def scalar(self, _statement):
            return SimpleNamespace(sector="Financial Services")

    monkeypatch.setattr(
        recommendation_inputs, "get_active_profile_payload", fake_profile
    )
    monkeypatch.setattr(
        recommendation_inputs, "get_latest_snapshot", fake_snapshot
    )

    loaded = await load_recommendation_inputs(
        session=FakeSession(),  # type: ignore[arg-type]
        user_id=user_id,
        ticker=" comi.ca ",
    )

    assert loaded.user_id == user_id
    assert loaded.ticker == "COMI.CA"
    assert loaded.profile == profile
    assert loaded.sector == "Financial Services"
    assert loaded.snapshot is not None
    assert loaded.snapshot.id == snapshot.id
    assert calls == [("profile", user_id), ("snapshot", "COMI.CA")]
    assert loaded.snapshot_status == "valid"


@pytest.mark.asyncio
async def test_newest_stale_snapshot_is_not_replaced_with_older_valid_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    user_id = uuid4()
    older_valid = _snapshot(date=date(2026, 11, 11))
    newest_stale = _snapshot(
        date=date(2026, 11, 12), data_quality_status="stale"
    )
    snapshot_calls: list[str] = []

    async def fake_profile(_session, _user_id):
        return _profile(user_id)

    async def fake_newest_snapshot(_session, _ticker):
        snapshot_calls.append("newest")
        return newest_stale

    async def fake_older_valid_snapshot(_session, _ticker):
        snapshot_calls.append("older_valid")
        return older_valid

    class FakeSession:
        async def scalar(self, _statement):
            return SimpleNamespace(sector="Financial Services")

    monkeypatch.setattr(
        recommendation_inputs, "get_active_profile_payload", fake_profile
    )
    monkeypatch.setattr(
        recommendation_inputs, "get_latest_snapshot", fake_newest_snapshot
    )
    monkeypatch.setattr(
        recommendation_inputs,
        "get_latest_valid_snapshot",
        fake_older_valid_snapshot,
        raising=False,
    )

    loaded = await load_recommendation_inputs(
        session=FakeSession(),  # type: ignore[arg-type]
        user_id=user_id,
        ticker="COMI.CA",
    )

    assert loaded.snapshot is None
    assert loaded.snapshot_status == "stale"
    assert snapshot_calls == ["newest"]


@pytest.mark.asyncio
async def test_input_adapter_allows_missing_profile_or_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def no_profile(_session, _user_id):
        return None

    async def no_snapshot(_session, _ticker):
        return None

    class FakeSession:
        async def scalar(self, _statement):
            return None

    monkeypatch.setattr(
        recommendation_inputs, "get_active_profile_payload", no_profile
    )
    monkeypatch.setattr(
        recommendation_inputs, "get_latest_snapshot", no_snapshot
    )

    loaded = await load_recommendation_inputs(
        session=FakeSession(),  # type: ignore[arg-type]
        user_id=uuid4(),
        ticker="COMI.CA",
    )

    assert loaded.profile is None
    assert loaded.snapshot is None
