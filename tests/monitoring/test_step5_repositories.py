"""Step 5 – Freshness validator, rule repository, and state repository tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio

from app.db.session import SessionLocal, engine
from app.monitoring.models.monitoring_rule import MonitoringRule
from app.monitoring.repositories import rule_repository, state_repository
from app.monitoring.schemas.market_data import MarketDataPoint, TechnicalSignals
from app.monitoring.schemas.rules import (
    RuleCreateRequest,
    RuleUpdateRequest,
    VolatilityThresholdParams,
)
from app.monitoring.services.freshness_validator import DataFreshnessValidator

# ── Helpers ────────────────────────────────────────────────────────────

NOW = datetime.now(tz=UTC)


def _market(updated_at: datetime | None = None) -> MarketDataPoint:
    return MarketDataPoint(
        ticker="AAPL",
        date=date(2024, 6, 15),
        open=148.0,
        high=155.0,
        low=147.0,
        close=150.0,
        volume=1_000_000,
        updated_at=updated_at or NOW,
    )


def _signals(calculated_at: datetime | None = None) -> TechnicalSignals:
    return TechnicalSignals(
        ticker="AAPL",
        date=date(2024, 6, 15),
        rsi=65.0,
        sma_20=150.0,
        sma_50=148.0,
        atr=3.2,
        composite_score=72.0,
        calculated_at=calculated_at or NOW,
    )


# ═══════════════════════════════════════════════════════════════════════
# DataFreshnessValidator (pure – no DB)
# ═══════════════════════════════════════════════════════════════════════


class TestDataFreshnessValidator:
    def test_fresh_data(self):
        ok, reason = DataFreshnessValidator.validate_freshness(
            _market(), _signals(), max_staleness_hours=36
        )
        assert ok is True
        assert reason == "Data is fresh"

    def test_stale_market_data(self):
        stale_ts = NOW - timedelta(hours=48)
        ok, reason = DataFreshnessValidator.validate_freshness(
            _market(updated_at=stale_ts), _signals(), max_staleness_hours=36
        )
        assert ok is False
        assert "stale" in reason.lower()

    def test_stale_signals(self):
        stale_ts = NOW - timedelta(hours=48)
        ok, reason = DataFreshnessValidator.validate_freshness(
            _market(), _signals(calculated_at=stale_ts), max_staleness_hours=36
        )
        assert ok is False
        assert "stale" in reason.lower()

    def test_none_market_data(self):
        ok, reason = DataFreshnessValidator.validate_freshness(
            None, _signals(), max_staleness_hours=36
        )
        assert ok is False
        assert "missing" in reason.lower()

    def test_none_signals(self):
        ok, reason = DataFreshnessValidator.validate_freshness(
            _market(), None, max_staleness_hours=36
        )
        assert ok is False
        assert "missing" in reason.lower()

    def test_both_none(self):
        ok, reason = DataFreshnessValidator.validate_freshness(
            None, None, max_staleness_hours=36
        )
        assert ok is False
        assert "both" in reason.lower()

    def test_boundary_just_within_max(self):
        """Data just within max_staleness_hours is considered fresh."""
        # Use 35h59m to avoid race between NOW capture and validator call
        boundary_ts = datetime.now(tz=UTC) - timedelta(hours=35, minutes=59)
        ok, _ = DataFreshnessValidator.validate_freshness(
            _market(updated_at=boundary_ts),
            _signals(calculated_at=boundary_ts),
            max_staleness_hours=36,
        )
        assert ok is True

    def test_boundary_just_beyond_max(self):
        """Data just past max_staleness_hours is stale."""
        boundary_ts = datetime.now(tz=UTC) - timedelta(hours=36, minutes=1)
        ok, _ = DataFreshnessValidator.validate_freshness(
            _market(updated_at=boundary_ts),
            _signals(calculated_at=boundary_ts),
            max_staleness_hours=36,
        )
        assert ok is False


# ═══════════════════════════════════════════════════════════════════════
# Database-backed tests (require running PostgreSQL)
# ═══════════════════════════════════════════════════════════════════════


@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def dispose_engine_pool():
    """Dispose connections after each test to avoid event-loop conflicts."""
    yield
    await engine.dispose()


@pytest.mark.asyncio
class TestRuleRepository:
    """CRUD operations on MonitoringRule via rule_repository."""

    async def test_create_rule(self):
        user_id = uuid4()
        req = RuleCreateRequest(
            name="RSI Alert",
            ticker="AAPL",
            parameters={
                "rule_type": "rsi_threshold",
                "threshold": 70,
                "direction": "above",
            },
            cooldown_minutes=30,
        )
        async with SessionLocal() as session, session.begin():
            rule = await rule_repository.create_rule(session, user_id, req)

            assert rule.id is not None
            assert rule.user_id == user_id
            assert rule.name == "RSI Alert"
            assert rule.ticker == "AAPL"
            assert rule.rule_type == "rsi_threshold"
            assert rule.parameters["threshold"] == 70
            assert rule.cooldown_minutes == 30
            assert rule.is_active is True

            await session.rollback()

    async def test_get_rule(self):
        user_id = uuid4()
        async with SessionLocal() as session, session.begin():
            rule = MonitoringRule(
                user_id=user_id,
                name="Get Test",
                ticker="MSFT",
                rule_type="rsi_threshold",
                parameters={"threshold": 50},
            )
            session.add(rule)
            await session.flush()

            fetched = await rule_repository.get_rule(session, rule.id, user_id)
            assert fetched is not None
            assert fetched.name == "Get Test"

            # Wrong user_id → None
            fetched_wrong = await rule_repository.get_rule(session, rule.id, uuid4())
            assert fetched_wrong is None

            await session.rollback()

    async def test_update_rule(self):
        user_id = uuid4()
        async with SessionLocal() as session, session.begin():
            rule = MonitoringRule(
                user_id=user_id,
                name="Old Name",
                ticker="GOOG",
                rule_type="rsi_threshold",
                parameters={"threshold": 50, "direction": "above"},
            )
            session.add(rule)
            await session.flush()

            req = RuleUpdateRequest(name="New Name", cooldown_minutes=120)
            updated = await rule_repository.update_rule(session, rule.id, user_id, req)
            assert updated is not None
            assert updated.name == "New Name"
            assert updated.cooldown_minutes == 120

            await session.rollback()

    async def test_update_rule_change_parameters(self):
        user_id = uuid4()
        async with SessionLocal() as session, session.begin():
            rule = MonitoringRule(
                user_id=user_id,
                name="Params test",
                ticker="TSLA",
                rule_type="rsi_threshold",
                parameters={"threshold": 70, "direction": "above"},
            )
            session.add(rule)
            await session.flush()

            new_params = VolatilityThresholdParams(atr_pct_threshold=3.0)
            req = RuleUpdateRequest(parameters=new_params)
            updated = await rule_repository.update_rule(session, rule.id, user_id, req)
            assert updated is not None
            assert updated.rule_type == "volatility_threshold"
            assert updated.parameters["atr_pct_threshold"] == 3.0

            await session.rollback()

    async def test_update_nonexistent_returns_none(self):
        async with SessionLocal() as session, session.begin():
            result = await rule_repository.update_rule(
                session, uuid4(), uuid4(), RuleUpdateRequest(name="X")
            )
            assert result is None
            await session.rollback()

    async def test_soft_delete_rule(self):
        user_id = uuid4()
        async with SessionLocal() as session, session.begin():
            rule = MonitoringRule(
                user_id=user_id,
                name="Delete Me",
                ticker="AMZN",
                rule_type="rsi_threshold",
                parameters={"threshold": 30},
            )
            session.add(rule)
            await session.flush()

            deleted = await rule_repository.soft_delete_rule(session, rule.id, user_id)
            assert deleted is True
            assert rule.is_active is False
            assert rule.deactivated_at is not None

            await session.rollback()

    async def test_soft_delete_nonexistent_returns_false(self):
        async with SessionLocal() as session, session.begin():
            result = await rule_repository.soft_delete_rule(session, uuid4(), uuid4())
            assert result is False
            await session.rollback()

    async def test_load_active_rules_grouped_by_ticker(self):
        user_id = uuid4()
        async with SessionLocal() as session, session.begin():
            for ticker, name in [
                ("AAPL", "R1"),
                ("AAPL", "R2"),
                ("MSFT", "R3"),
            ]:
                session.add(
                    MonitoringRule(
                        user_id=user_id,
                        name=name,
                        ticker=ticker,
                        rule_type="rsi_threshold",
                        parameters={"threshold": 70},
                    )
                )
            # Add an inactive rule that should be excluded
            session.add(
                MonitoringRule(
                    user_id=user_id,
                    name="Inactive",
                    ticker="AAPL",
                    rule_type="rsi_threshold",
                    parameters={"threshold": 30},
                    is_active=False,
                )
            )
            await session.flush()

            grouped = await rule_repository.load_active_rules_grouped_by_ticker(session)
            # At least our freshly inserted active rules
            assert "AAPL" in grouped
            assert "MSFT" in grouped
            aapl_names = {r.name for r in grouped["AAPL"]}
            assert "R1" in aapl_names
            assert "R2" in aapl_names
            assert "Inactive" not in aapl_names

            await session.rollback()


@pytest.mark.asyncio
class TestStateRepository:
    """get_state / upsert_state tests with actual DB."""

    async def test_get_state_returns_none_when_missing(self):
        async with SessionLocal() as session, session.begin():
            state = await state_repository.get_state(session, uuid4())
            assert state is None
            await session.rollback()

    async def test_upsert_state_insert(self):
        user_id = uuid4()
        async with SessionLocal() as session, session.begin():
            # Need a parent rule for the FK
            rule = MonitoringRule(
                user_id=user_id,
                name="State Test",
                ticker="AAPL",
                rule_type="rsi_threshold",
                parameters={"threshold": 70},
            )
            session.add(rule)
            await session.flush()

            state = await state_repository.upsert_state(
                session,
                rule.id,
                last_value=72.3,
                last_threshold_value=70.0,
                last_triggered=True,
                consecutive_triggers=1,
                state_data={"price_above_sma": True},
            )

            assert state is not None
            assert state.rule_id == rule.id
            assert state.last_value == 72.3
            assert state.last_triggered is True
            assert state.consecutive_triggers == 1
            assert state.state_data["price_above_sma"] is True

            await session.rollback()

    async def test_upsert_state_update(self):
        user_id = uuid4()
        async with SessionLocal() as session, session.begin():
            rule = MonitoringRule(
                user_id=user_id,
                name="Upsert Update Test",
                ticker="MSFT",
                rule_type="rsi_threshold",
                parameters={"threshold": 30},
            )
            session.add(rule)
            await session.flush()

            # First insert
            await state_repository.upsert_state(
                session,
                rule.id,
                last_value=25.0,
                last_triggered=True,
                consecutive_triggers=1,
                state_data={"v": 1},
            )

            # Second upsert (update)
            state = await state_repository.upsert_state(
                session,
                rule.id,
                last_value=55.0,
                last_triggered=False,
                consecutive_triggers=0,
                state_data={"v": 2},
            )

            assert state.last_value == 55.0
            assert state.last_triggered is False
            assert state.consecutive_triggers == 0
            assert state.state_data["v"] == 2

            await session.rollback()

    async def test_get_state_after_upsert(self):
        user_id = uuid4()
        async with SessionLocal() as session, session.begin():
            rule = MonitoringRule(
                user_id=user_id,
                name="Get After Upsert",
                ticker="GOOG",
                rule_type="rsi_threshold",
                parameters={"threshold": 50},
            )
            session.add(rule)
            await session.flush()

            await state_repository.upsert_state(
                session,
                rule.id,
                last_value=42.0,
                state_data={"key": "val"},
            )

            fetched = await state_repository.get_state(session, rule.id)
            assert fetched is not None
            assert fetched.last_value == 42.0
            assert fetched.state_data["key"] == "val"

            await session.rollback()
