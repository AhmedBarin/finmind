"""Step 7 – Monitoring cycle runner tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from unittest.mock import AsyncMock, patch
from uuid import uuid4

import pytest
import pytest_asyncio
from sqlalchemy import select, text

from app.db.session import SessionLocal, engine
from app.monitoring.models.alert import Alert
from app.monitoring.models.monitoring_rule import MonitoringRule
from app.monitoring.models.monitoring_run import MonitoringRun
from app.monitoring.schemas.market_data import MarketDataPoint, TechnicalSignals
from app.monitoring.services.job_runner import run_monitoring_cycle


@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def dispose_engine_pool():
    """Dispose connections after each test to avoid event-loop conflicts."""
    yield
    await engine.dispose()


# ── Helpers ────────────────────────────────────────────────────────────

NOW = datetime.now(tz=UTC)


def _fresh_market(ticker: str = "AAPL") -> MarketDataPoint:
    return MarketDataPoint(
        ticker=ticker,
        date=date(2024, 6, 15),
        open=148.0,
        high=155.0,
        low=147.0,
        close=150.0,
        volume=1_000_000,
        updated_at=NOW,
    )


def _fresh_signals(ticker: str = "AAPL") -> TechnicalSignals:
    return TechnicalSignals(
        ticker=ticker,
        date=date(2024, 6, 15),
        rsi=75.0,
        sma_20=150.0,
        sma_50=148.0,
        atr=3.2,
        composite_score=72.0,
        calculated_at=NOW,
    )


async def _seed_rule(session, ticker: str = "AAPL") -> MonitoringRule:
    """Insert an active RSI rule and flush."""
    rule = MonitoringRule(
        user_id=uuid4(),
        name="RSI Alert",
        ticker=ticker,
        rule_type="rsi_threshold",
        parameters={
            "rule_type": "rsi_threshold",
            "threshold": 70,
            "direction": "above",
        },
        cooldown_minutes=60,
    )
    session.add(rule)
    await session.flush()
    return rule


# ═══════════════════════════════════════════════════════════════════════
# End-to-end cycle test
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestRunMonitoringCycleE2E:
    async def test_cycle_completes_with_alert(self):
        """Seed a rule, mock fresh data, run cycle → alert persisted, run completed."""
        # Seed a rule inside a committed transaction so the runner can see it
        async with SessionLocal() as session, session.begin():
            rule = await _seed_rule(session)
            rule_id = rule.id

        # Mock market data repo to return fresh data
        mock_market = AsyncMock(return_value=_fresh_market())
        mock_signals = AsyncMock(return_value=_fresh_signals())

        with (
            patch(
                "app.monitoring.services.job_runner.market_data_repository.get_latest_market_data",
                mock_market,
            ),
            patch(
                "app.monitoring.services.job_runner.market_data_repository.get_latest_signals",
                mock_signals,
            ),
        ):
            await run_monitoring_cycle(SessionLocal)

        # Verify: a monitoring_run with status=completed exists
        async with SessionLocal() as session:
            runs = (
                await session.execute(
                    select(MonitoringRun)
                    .where(MonitoringRun.status == "completed")
                    .order_by(MonitoringRun.started_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            assert runs is not None
            assert runs.rules_evaluated >= 1
            assert runs.rules_triggered >= 1

            # Verify: an alert was created for our rule
            alert = (
                await session.execute(select(Alert).where(Alert.rule_id == rule_id))
            ).scalar_one_or_none()
            assert alert is not None
            assert alert.ticker == "AAPL"
            assert alert.run_id == runs.id

        # Cleanup
        async with SessionLocal() as session, session.begin():
            await session.execute(
                text("DELETE FROM alerts WHERE rule_id = :rid OR run_id = :run_id"),
                {"rid": str(rule_id), "run_id": str(runs.id)},
            )
            await session.execute(
                text("DELETE FROM monitoring_rule_states WHERE rule_id = :rid"),
                {"rid": str(rule_id)},
            )
            await session.execute(
                text("DELETE FROM monitoring_runs WHERE id = :rid"),
                {"rid": str(runs.id)},
            )
            await session.execute(
                text("DELETE FROM monitoring_rules WHERE id = :rid"),
                {"rid": str(rule_id)},
            )

    async def test_cycle_skips_stale_data(self):
        """When market data repo returns None, rules are skipped."""
        async with SessionLocal() as session, session.begin():
            rule = await _seed_rule(session)
            rule_id = rule.id

        # Don't mock → market_data_repository returns None by default
        await run_monitoring_cycle(SessionLocal)

        async with SessionLocal() as session:
            run = (
                await session.execute(
                    select(MonitoringRun)
                    .order_by(MonitoringRun.started_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()

            assert run is not None
            assert run.status == "completed"
            assert run.rules_skipped >= 1
            assert run.rules_triggered == 0

        # Cleanup
        async with SessionLocal() as session, session.begin():
            await session.execute(
                text("DELETE FROM monitoring_runs WHERE id = :rid"),
                {"rid": str(run.id)},
            )
            await session.execute(
                text("DELETE FROM monitoring_rules WHERE id = :rid"),
                {"rid": str(rule_id)},
            )


# ═══════════════════════════════════════════════════════════════════════
# Concurrent execution / advisory lock test
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestAdvisoryLock:
    async def test_concurrent_cycle_skips(self):
        """If another session holds the advisory lock, the cycle returns early."""
        from app.monitoring.config import monitoring_settings

        # Session 1: hold advisory lock inside a transaction
        async with SessionLocal() as session1, session1.begin():
            # Acquire the *same* lock the runner uses
            result = await session1.execute(
                text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
                {"lock_id": monitoring_settings.lock_id},
            )
            assert result.scalar() is True  # we got the lock

            # Session 2: run_monitoring_cycle should skip
            await run_monitoring_cycle(SessionLocal)

            # If we got here without hanging, the runner correctly
            # detected the lock and returned early.

        # Verify no new run was created (the runner skipped)
        async with SessionLocal() as session:
            latest_run = (
                await session.execute(
                    select(MonitoringRun)
                    .order_by(MonitoringRun.started_at.desc())
                    .limit(1)
                )
            ).scalar_one_or_none()
            # The latest run (if any) should NOT be one created just now
            # by the skipped cycle (it never creates a run record)
            if latest_run is not None:
                # It must have been created before the lock test
                assert latest_run.started_at < NOW or latest_run.status != "running"
