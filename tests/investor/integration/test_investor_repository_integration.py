"""Integration tests for Investor Agent repository persistence in PostgreSQL."""

from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy.exc import SQLAlchemyError

from app.db.session import SessionLocal, engine
from app.investor.repository import (
    confirm_and_activate_profile,
    get_active_profile_payload,
    get_profile_history,
    list_audit_logs,
    list_learned_preferences,
    update_profile_constraints,
    upsert_learned_preference,
)
from app.investor.schemas import (
    ConstraintsUpdateRequest,
    InvestmentExperience,
    InvestmentGoal,
    InvestmentHorizon,
    InvestorProfileConfirmRequest,
    LearnedPreferenceCreate,
    RiskProfile,
)


@pytest_asyncio.fixture
async def db_session():
    try:
        async with engine.connect():
            pass
    except (OSError, SQLAlchemyError) as exc:
        await engine.dispose()
        pytest.skip(f"PostgreSQL not reachable for integration tests: {type(exc).__name__}")

    try:
        async with SessionLocal() as session:
            transaction = await session.begin()
            try:
                yield session
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_profile_lifecycle_audit_and_learned_preferences(db_session) -> None:
    user_id = uuid4()

    v1 = await confirm_and_activate_profile(
        db_session,
        user_id,
        InvestorProfileConfirmRequest(
            risk_profile=RiskProfile.CONSERVATIVE,
            investment_horizon=InvestmentHorizon.LONG,
            investment_goal=InvestmentGoal.CAPITAL_PRESERVATION,
            investment_experience=InvestmentExperience.BEGINNER,
            excluded_sectors=["Tobacco"],
        ),
        reason="Initial HITL confirmation",
    )
    assert v1.profile_version == 1
    assert v1.is_active is True

    v2 = await confirm_and_activate_profile(
        db_session,
        user_id,
        InvestorProfileConfirmRequest(
            risk_profile=RiskProfile.MODERATE,
            investment_horizon=InvestmentHorizon.MEDIUM,
            investment_goal=InvestmentGoal.GROWTH,
            investment_experience=InvestmentExperience.INTERMEDIATE,
        ),
        reason="Re-profiling after review",
    )
    assert v2.profile_version == 2
    assert v2.is_active is True

    v3 = await update_profile_constraints(
        db_session,
        user_id,
        ConstraintsUpdateRequest(
            excluded_tickers=["comi"],
            reason="Exclude COMI",
        ),
    )
    assert v3 is not None
    assert v3.profile_version == 3
    assert v3.excluded_tickers == ["COMI"]

    payload = await get_active_profile_payload(db_session, user_id)
    assert payload is not None
    assert payload.risk_profile is RiskProfile.MODERATE
    assert payload.liquidity_floor_pct == 70.0
    assert payload.excluded_tickers == ["COMI"]

    history = await get_profile_history(db_session, user_id)
    assert [row.profile_version for row in history] == [3, 1]
    assert history[0].is_active is True
    assert history[1].is_active is False

    audits = await list_audit_logs(db_session, user_id)
    assert len(audits) == 3

    pref = await upsert_learned_preference(
        db_session,
        user_id,
        LearnedPreferenceCreate(
            preference_key="dividend_focused",
            preference_value={"preferred": True},
            confidence_score=0.90,
            source_event="conversation",
        ),
    )
    assert pref.preference_key == "dividend_focused"
    prefs = await list_learned_preferences(db_session, user_id)
    assert len(prefs) == 1

