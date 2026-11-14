"""Unit tests for Investor Agent repository logic using an async session fake."""

from datetime import UTC, datetime
from decimal import Decimal
from uuid import uuid4

import pytest

from app.investor.models import InvestorProfile, ProfileAuditLog
from app.investor.repository import (
    confirm_and_activate_profile,
    get_active_profile_payload,
    update_profile_constraints,
)
from app.investor.schemas import (
    ConstraintsUpdateRequest,
    InvestmentExperience,
    InvestmentGoal,
    InvestmentHorizon,
    InvestorProfileConfirmRequest,
    RiskProfile,
)


class _ScalarResult:
    def __init__(self, value) -> None:
        self._value = value

    def scalar_one_or_none(self):
        return self._value

    def scalar_one(self):
        return self._value


class _FakeAsyncSession:
    def __init__(self, execute_results: list) -> None:
        self._results = list(execute_results)
        self.added: list = []
        self.flushed = 0
        self.refreshed: list = []

    async def execute(self, stmt):
        return _ScalarResult(self._results.pop(0))

    def add(self, obj) -> None:
        if getattr(obj, "id", None) is None:
            obj.id = uuid4()
        if isinstance(obj, InvestorProfile) and obj.confirmed_at is None:
            obj.confirmed_at = datetime.now(UTC)
        self.added.append(obj)

    async def flush(self) -> None:
        self.flushed += 1

    async def refresh(self, obj) -> None:
        self.refreshed.append(obj)


@pytest.mark.asyncio
async def test_confirm_initial_profile_creates_profile_and_audit_log() -> None:
    user_id = uuid4()
    session = _FakeAsyncSession(execute_results=[None, 0])
    confirmation = InvestorProfileConfirmRequest(
        risk_profile=RiskProfile.MODERATE,
        investment_horizon=InvestmentHorizon.MEDIUM,
        investment_goal=InvestmentGoal.GROWTH,
        investment_experience=InvestmentExperience.INTERMEDIATE,
        excluded_tickers=["comi"],
    )

    profile = await confirm_and_activate_profile(
        session,  # type: ignore[arg-type]
        user_id,
        confirmation,
    )

    assert profile.user_id == user_id
    assert profile.profile_version == 1
    assert profile.is_active is True
    assert profile.liquidity_floor_pct == Decimal("70.00")
    assert profile.max_atr_pctl_cap == Decimal("75.00")
    assert profile.excluded_tickers == ["COMI"]

    audit = next(obj for obj in session.added if isinstance(obj, ProfileAuditLog))
    assert audit.change_type == "initial_creation"
    assert audit.previous_state is None
    assert audit.new_state["profile_version"] == 1
    assert audit.new_state["risk_profile"] == "moderate"


@pytest.mark.asyncio
async def test_reconfirm_profile_deactivates_previous_and_increments_version() -> None:
    user_id = uuid4()
    prior = InvestorProfile(
        id=uuid4(),
        user_id=user_id,
        risk_profile="conservative",
        investment_horizon="long",
        investment_goal="capital_preservation",
        investment_experience="beginner",
        liquidity_floor_pct=Decimal("50.00"),
        max_atr_pctl_cap=Decimal("60.00"),
        excluded_sectors=[],
        excluded_tickers=[],
        preferred_sectors=[],
        is_active=True,
        profile_version=2,
        confirmed_at=datetime.now(UTC),
    )
    session = _FakeAsyncSession(execute_results=[prior, 2])
    confirmation = InvestorProfileConfirmRequest(
        risk_profile=RiskProfile.AGGRESSIVE,
        investment_horizon=InvestmentHorizon.SHORT,
        investment_goal=InvestmentGoal.SPECULATION,
        investment_experience=InvestmentExperience.ADVANCED,
    )

    updated = await confirm_and_activate_profile(
        session,  # type: ignore[arg-type]
        user_id,
        confirmation,
        reason="User completed re-profiling",
    )

    assert prior.is_active is False
    assert updated.profile_version == 3
    assert updated.liquidity_floor_pct == Decimal("85.00")
    assert updated.max_atr_pctl_cap == Decimal("90.00")
    # Prior deactivation must flush before inserting new active profile.
    assert session.flushed >= 3

    audit = next(obj for obj in session.added if isinstance(obj, ProfileAuditLog))
    assert audit.change_type == "re_profiling"
    assert audit.previous_state is not None
    assert audit.previous_state["risk_profile"] == "conservative"
    assert audit.new_state["risk_profile"] == "aggressive"
    assert audit.reason == "User completed re-profiling"


@pytest.mark.asyncio
async def test_update_constraints_missing_returns_none_and_present_audits() -> None:
    user_id = uuid4()
    empty_session = _FakeAsyncSession(execute_results=[None])
    assert (
        await update_profile_constraints(
            empty_session,  # type: ignore[arg-type]
            user_id,
            ConstraintsUpdateRequest(excluded_sectors=["Tobacco"]),
        )
        is None
    )

    active = InvestorProfile(
        id=uuid4(),
        user_id=user_id,
        risk_profile="moderate",
        investment_horizon="medium",
        investment_goal="growth",
        investment_experience="intermediate",
        liquidity_floor_pct=Decimal("70.00"),
        max_atr_pctl_cap=Decimal("75.00"),
        excluded_sectors=[],
        excluded_tickers=[],
        preferred_sectors=[],
        is_active=True,
        profile_version=1,
        confirmed_at=datetime.now(UTC),
    )
    session = _FakeAsyncSession(execute_results=[active])
    updated = await update_profile_constraints(
        session,  # type: ignore[arg-type]
        user_id,
        ConstraintsUpdateRequest(
            excluded_sectors=["Tobacco"],
            excluded_tickers=["efid"],
            reason="Exclude tobacco",
        ),
    )

    assert updated is active
    assert active.profile_version == 2
    assert active.excluded_sectors == ["Tobacco"]
    assert active.excluded_tickers == ["EFID"]
    audit = next(obj for obj in session.added if isinstance(obj, ProfileAuditLog))
    assert audit.change_type == "user_edit"
    assert audit.previous_state["excluded_sectors"] == []
    assert audit.new_state["excluded_sectors"] == ["Tobacco"]


@pytest.mark.asyncio
async def test_get_active_profile_payload_validates_orm_model() -> None:
    user_id = uuid4()
    active = InvestorProfile(
        id=uuid4(),
        user_id=user_id,
        risk_profile="conservative",
        investment_horizon="long",
        investment_goal="income",
        investment_experience="beginner",
        liquidity_floor_pct=Decimal("50.00"),
        max_atr_pctl_cap=Decimal("60.00"),
        excluded_sectors=["Tobacco"],
        excluded_tickers=["COMI"],
        preferred_sectors=["Banking"],
        is_active=True,
        profile_version=1,
        confirmed_at=datetime.now(UTC),
    )
    session = _FakeAsyncSession(execute_results=[active])
    payload = await get_active_profile_payload(session, user_id)  # type: ignore[arg-type]

    assert payload is not None
    assert payload.risk_profile == RiskProfile.CONSERVATIVE
    assert payload.liquidity_floor_pct == 50.0
    assert payload.max_atr_pctl_cap == 60.0

