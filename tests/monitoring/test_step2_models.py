from uuid import uuid4

import pytest
import pytest_asyncio

from app.db.base import Base
from app.db.session import SessionLocal, engine
from app.monitoring.models import (
    Alert,
    MonitoringRule,
    MonitoringRuleState,
    MonitoringRun,
)


@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def dispose_engine_pool():
    """Ensure connections in pool are disposed per function test to avoid event loop conflicts."""
    yield
    await engine.dispose()


class TestMonitoringRuleModel:
    """Verify MonitoringRule model metadata."""

    def test_table_name(self) -> None:
        assert MonitoringRule.__tablename__ == "monitoring_rules"

    def test_columns_exist(self) -> None:
        columns = {c.name for c in MonitoringRule.__table__.columns}
        expected = {
            "id",
            "user_id",
            "name",
            "ticker",
            "rule_type",
            "parameters",
            "is_active",
            "cooldown_minutes",
            "created_at",
            "updated_at",
            "deactivated_at",
        }
        assert expected == columns

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in MonitoringRule.__table__.primary_key.columns]
        assert pk_cols == ["id"]

    def test_indexes(self) -> None:
        index_names = {idx.name for idx in MonitoringRule.__table__.indexes}
        assert "ix_monitoring_rules_user_id" in index_names
        assert "ix_monitoring_rules_ticker" in index_names
        assert "ix_monitoring_rules_is_active" in index_names


class TestMonitoringRuleStateModel:
    """Verify MonitoringRuleState model metadata."""

    def test_table_name(self) -> None:
        assert MonitoringRuleState.__tablename__ == "monitoring_rule_states"

    def test_columns_exist(self) -> None:
        columns = {c.name for c in MonitoringRuleState.__table__.columns}
        expected = {
            "rule_id",
            "last_evaluated_at",
            "last_value",
            "last_threshold_value",
            "last_triggered",
            "consecutive_triggers",
            "state_data",
        }
        assert expected == columns

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in MonitoringRuleState.__table__.primary_key.columns]
        assert pk_cols == ["rule_id"]

    def test_foreign_key(self) -> None:
        fk_targets = [
            next(iter(c.foreign_keys)).target_fullname
            for c in MonitoringRuleState.__table__.columns
            if c.foreign_keys
        ]
        assert "monitoring_rules.id" in fk_targets


class TestMonitoringRunModel:
    """Verify MonitoringRun model metadata."""

    def test_table_name(self) -> None:
        assert MonitoringRun.__tablename__ == "monitoring_runs"

    def test_columns_exist(self) -> None:
        columns = {c.name for c in MonitoringRun.__table__.columns}
        expected = {
            "id",
            "started_at",
            "finished_at",
            "status",
            "rules_evaluated",
            "rules_triggered",
            "rules_skipped",
            "rules_errored",
            "error_message",
        }
        assert expected == columns

    def test_primary_key(self) -> None:
        pk_cols = [c.name for c in MonitoringRun.__table__.primary_key.columns]
        assert pk_cols == ["id"]


class TestAlertModel:
    """Verify Alert model metadata."""

    def test_table_name(self) -> None:
        assert Alert.__tablename__ == "alerts"

    def test_columns_exist(self) -> None:
        columns = {c.name for c in Alert.__table__.columns}
        expected = {
            "id",
            "rule_id",
            "user_id",
            "ticker",
            "alert_type",
            "severity",
            "reason",
            "evidence",
            "current_value",
            "threshold_value",
            "run_id",
            "created_at",
            "acknowledged_at",
        }
        assert expected == columns

    def test_foreign_keys(self) -> None:
        fk_targets = set()
        for col in Alert.__table__.columns:
            for fk in col.foreign_keys:
                fk_targets.add(fk.target_fullname)
        assert "monitoring_rules.id" in fk_targets
        assert "monitoring_runs.id" in fk_targets

    def test_indexes(self) -> None:
        index_names = {idx.name for idx in Alert.__table__.indexes}
        assert "ix_alerts_user_id" in index_names
        assert "ix_alerts_ticker" in index_names
        assert "uq_alert_daily" in index_names


class TestModelsRegistered:
    """Verify all monitoring models are registered in Base.metadata."""

    def test_all_tables_in_metadata(self) -> None:
        table_names = set(Base.metadata.tables.keys())
        expected = {
            "monitoring_rules",
            "monitoring_rule_states",
            "monitoring_runs",
            "alerts",
        }
        assert expected.issubset(table_names)


@pytest.mark.asyncio
class TestDatabaseRoundTrip:
    """Verify inserting and rolling back test records using SessionLocal."""

    async def test_insert_and_rollback_monitoring_rule(self) -> None:
        rule_id = uuid4()
        user_id = uuid4()
        async with SessionLocal() as session:
            rule = MonitoringRule(
                id=rule_id,
                user_id=user_id,
                name="Test PE ratio threshold",
                ticker="2010",
                rule_type="pe_ratio",
                parameters={"threshold": 15.0},
                is_active=True,
                cooldown_minutes=60,
            )
            session.add(rule)
            await session.flush()

            # Record was added and flushed
            assert rule.id == rule_id
            assert rule.is_active is True
            assert rule.cooldown_minutes == 60

            # Roll back transaction
            await session.rollback()

            # Verify it was rolled back and not persisted
            result = await session.get(MonitoringRule, rule_id)
            assert result is None

    async def test_insert_and_rollback_monitoring_run(self) -> None:
        run_id = uuid4()
        async with SessionLocal() as session:
            run = MonitoringRun(
                id=run_id,
                status="running",
                rules_evaluated=5,
                rules_triggered=1,
                rules_skipped=0,
                rules_errored=0,
            )
            session.add(run)
            await session.flush()

            assert run.id == run_id
            assert run.status == "running"
            assert run.rules_evaluated == 5

            await session.rollback()

            result = await session.get(MonitoringRun, run_id)
            assert result is None

    async def test_insert_and_rollback_alert_with_rule(self) -> None:
        rule_id = uuid4()
        alert_id = uuid4()
        user_id = uuid4()
        async with SessionLocal() as session:
            rule = MonitoringRule(
                id=rule_id,
                user_id=user_id,
                name="Debt alert rule",
                ticker="4001",
                rule_type="debt_ratio",
                parameters={"threshold": 2.0},
            )
            session.add(rule)
            await session.flush()

            alert = Alert(
                id=alert_id,
                rule_id=rule.id,
                user_id=user_id,
                ticker="4001",
                alert_type="debt_ratio",
                severity="warning",
                reason="Debt-to-equity exceeded threshold",
                evidence={"ratio": 2.5},
                current_value=2.5,
                threshold_value=2.0,
            )
            session.add(alert)
            await session.flush()

            assert alert.id == alert_id
            assert alert.rule_id == rule_id

            await session.rollback()

            result_alert = await session.get(Alert, alert_id)
            result_rule = await session.get(MonitoringRule, rule_id)
            assert result_alert is None
            assert result_rule is None

    async def test_insert_and_rollback_rule_state(self) -> None:
        rule_id = uuid4()
        user_id = uuid4()
        async with SessionLocal() as session:
            rule = MonitoringRule(
                id=rule_id,
                user_id=user_id,
                name="State test rule",
                ticker="1010",
                rule_type="price_spike",
                parameters={"pct": 5.0},
            )
            session.add(rule)
            await session.flush()

            state = MonitoringRuleState(
                rule_id=rule.id,
                last_value=42.5,
                last_threshold_value=40.0,
                last_triggered=True,
                consecutive_triggers=1,
                state_data={"last_spike_pct": 6.2},
            )
            session.add(state)
            await session.flush()

            assert state.rule_id == rule_id
            assert state.last_value == 42.5
            assert state.consecutive_triggers == 1

            await session.rollback()

            result_state = await session.get(MonitoringRuleState, rule_id)
            result_rule = await session.get(MonitoringRule, rule_id)
            assert result_state is None
            assert result_rule is None
