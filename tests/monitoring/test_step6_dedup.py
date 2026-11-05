"""Step 6 – Alert deduplication, alert service, and notification dispatcher tests."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio

from app.db.session import SessionLocal, engine
from app.monitoring.models.alert import Alert
from app.monitoring.models.monitoring_rule import MonitoringRule
from app.monitoring.models.monitoring_run import MonitoringRun
from app.monitoring.schemas.market_data import EvaluationResult
from app.monitoring.services.alert_service import AlertService
from app.monitoring.services.deduplication_service import AlertDeduplicationService
from app.monitoring.services.notification_dispatcher import (
    NoOpNotificationDispatcher,
)


@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def dispose_engine_pool():
    """Dispose connections after each test to avoid event-loop conflicts."""
    yield
    await engine.dispose()


# ── Helpers ────────────────────────────────────────────────────────────


def _make_rule(
    user_id: uuid4 | None = None,
    cooldown_minutes: int = 60,
) -> MonitoringRule:
    """Create an in-memory MonitoringRule (not yet persisted)."""
    return MonitoringRule(
        user_id=user_id or uuid4(),
        name="Test Rule",
        ticker="AAPL",
        rule_type="rsi_threshold",
        parameters={"threshold": 70, "direction": "above"},
        cooldown_minutes=cooldown_minutes,
    )


def _eval_result(triggered: bool = True) -> EvaluationResult:
    return EvaluationResult(
        triggered=triggered,
        reason="RSI 75 is above threshold 70",
        current_value=75.0,
        threshold_value=70.0,
        evidence={"rsi": 75.0, "threshold": 70.0},
    )


# ═══════════════════════════════════════════════════════════════════════
# AlertDeduplicationService
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestAlertDeduplicationService:
    async def test_no_prior_alert_not_duplicate(self):
        """No alerts for a brand-new rule → is_duplicate returns False."""
        async with SessionLocal() as session, session.begin():
            rule = _make_rule()
            session.add(rule)
            await session.flush()

            is_dup = await AlertDeduplicationService.is_duplicate(session, rule)
            assert is_dup is False

            await session.rollback()

    async def test_recent_alert_is_duplicate(self):
        """Alert within cooldown window → is_duplicate returns True."""
        async with SessionLocal() as session, session.begin():
            rule = _make_rule(cooldown_minutes=60)
            session.add(rule)
            await session.flush()

            # Insert an alert with server-default created_at (now)
            alert = Alert(
                rule_id=rule.id,
                user_id=rule.user_id,
                ticker=rule.ticker,
                alert_type=rule.rule_type,
                severity="INFO",
                reason="Test alert",
                evidence={},
            )
            session.add(alert)
            await session.flush()

            is_dup = await AlertDeduplicationService.is_duplicate(session, rule)
            assert is_dup is True

            await session.rollback()

    async def test_old_alert_not_duplicate(self):
        """Alert older than cooldown window → is_duplicate returns False."""
        async with SessionLocal() as session, session.begin():
            rule = _make_rule(cooldown_minutes=60)
            session.add(rule)
            await session.flush()

            # Insert an alert with created_at well in the past
            old_time = datetime.now(tz=UTC) - timedelta(hours=3)
            alert = Alert(
                rule_id=rule.id,
                user_id=rule.user_id,
                ticker=rule.ticker,
                alert_type=rule.rule_type,
                severity="INFO",
                reason="Old alert",
                evidence={},
                created_at=old_time,
            )
            session.add(alert)
            await session.flush()

            is_dup = await AlertDeduplicationService.is_duplicate(session, rule)
            assert is_dup is False

            await session.rollback()


# ═══════════════════════════════════════════════════════════════════════
# AlertService
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestAlertService:
    async def test_create_alert_success(self):
        """Normal alert creation persists and returns the Alert row."""
        async with SessionLocal() as session, session.begin():
            rule = _make_rule()
            session.add(rule)
            await session.flush()

            alert = await AlertService.create_alert(session, rule, _eval_result())
            assert alert is not None
            assert alert.rule_id == rule.id
            assert alert.ticker == "AAPL"
            assert alert.severity == "INFO"  # 75/70 ≈ 1.07, below 1.5
            assert alert.reason == "RSI 75 is above threshold 70"

            await session.rollback()

    async def test_create_alert_with_run_id(self):
        """Alert linked to a monitoring run."""
        async with SessionLocal() as session, session.begin():
            rule = _make_rule()
            session.add(rule)
            await session.flush()

            run = MonitoringRun(
                status="running",
                rules_evaluated=1,
                rules_triggered=1,
                rules_skipped=0,
                rules_errored=0,
            )
            session.add(run)
            await session.flush()

            alert = await AlertService.create_alert(
                session, rule, _eval_result(), run_id=run.id
            )
            assert alert is not None
            assert alert.run_id == run.id

            await session.rollback()

    async def test_create_alert_duplicate_returns_none(self):
        """Duplicate alert (same rule+ticker+day) returns None gracefully."""
        async with SessionLocal() as session, session.begin():
            rule = _make_rule()
            session.add(rule)
            await session.flush()

            # First alert succeeds
            first = await AlertService.create_alert(session, rule, _eval_result())
            assert first is not None

            # Second alert for same rule+ticker+day → unique constraint
            second = await AlertService.create_alert(session, rule, _eval_result())
            assert second is None

            await session.rollback()

    async def test_create_alert_severity_info(self):
        """Low-ratio result → INFO severity."""
        async with SessionLocal() as session, session.begin():
            rule = _make_rule()
            session.add(rule)
            await session.flush()

            result = EvaluationResult(
                triggered=True,
                reason="RSI 31 is above threshold 30",
                current_value=31.0,
                threshold_value=30.0,
                evidence={},
            )
            alert = await AlertService.create_alert(session, rule, result)
            assert alert is not None
            assert alert.severity == "INFO"

            await session.rollback()

    async def test_create_alert_severity_warning_on_error(self):
        """Error result → WARNING severity."""
        async with SessionLocal() as session, session.begin():
            rule = _make_rule()
            session.add(rule)
            await session.flush()

            result = EvaluationResult(
                triggered=False,
                reason="Evaluation failed",
                error=True,
                error_message="data unavailable",
                evidence={},
            )
            alert = await AlertService.create_alert(session, rule, result)
            assert alert is not None
            assert alert.severity == "WARNING"

            await session.rollback()


# ═══════════════════════════════════════════════════════════════════════
# NoOpNotificationDispatcher
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestNoOpNotificationDispatcher:
    async def test_dispatch_logs_info(self, caplog):
        """NoOpNotificationDispatcher logs the alert at INFO level."""
        async with SessionLocal() as session, session.begin():
            rule = _make_rule()
            session.add(rule)
            await session.flush()

            alert = Alert(
                rule_id=rule.id,
                user_id=rule.user_id,
                ticker="AAPL",
                alert_type="rsi_threshold",
                severity="INFO",
                reason="Test dispatch",
                evidence={},
            )
            session.add(alert)
            await session.flush()

            dispatcher = NoOpNotificationDispatcher()
            with caplog.at_level("INFO"):
                await dispatcher.dispatch(alert)

            assert any("no-op" in r.message.lower() for r in caplog.records)

            await session.rollback()
