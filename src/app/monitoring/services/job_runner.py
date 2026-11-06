"""Central monitoring-cycle runner.

Orchestrates advisory locking, rule evaluation, deduplication, alert
persistence, and state updates in a single transactional sweep.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from pydantic import TypeAdapter
from sqlalchemy import text

from app.monitoring.config import monitoring_settings
from app.monitoring.evaluators.evaluator_dispatch import evaluate_rule
from app.monitoring.models.monitoring_run import MonitoringRun
from app.monitoring.repositories import market_data_repository, state_repository
from app.monitoring.repositories.rule_repository import (
    load_active_rules_grouped_by_ticker,
)
from app.monitoring.schemas.rules import RuleParams
from app.monitoring.services.alert_service import AlertService
from app.monitoring.services.deduplication_service import AlertDeduplicationService
from app.monitoring.services.freshness_validator import DataFreshnessValidator

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

logger = logging.getLogger(__name__)

_rule_params_adapter: TypeAdapter[RuleParams] = TypeAdapter(RuleParams)


async def run_monitoring_cycle(
    session_factory: async_sessionmaker[AsyncSession],
) -> None:
    """Execute one full monitoring sweep.

    1. Acquire a PostgreSQL transaction-level advisory lock to prevent
       concurrent runs.
    2. Create a ``monitoring_runs`` record.
    3. For every active rule, fetch market data, check freshness, evaluate,
       de-duplicate, persist alerts, and upsert state.
    4. Finalise the run record with counts and status.
    """
    async with session_factory() as session, session.begin():
        # ── Advisory lock ──────────────────────────────────────────
        lock_result = await session.execute(
            text("SELECT pg_try_advisory_xact_lock(:lock_id)"),
            {"lock_id": monitoring_settings.lock_id},
        )
        acquired = lock_result.scalar()
        if not acquired:
            logger.info("Monitoring cycle already running, skipping")
            return

        # ── Book-keeping ───────────────────────────────────────────
        run = MonitoringRun(status="running")
        session.add(run)
        await session.flush()

        rules_evaluated = 0
        rules_triggered = 0
        rules_skipped = 0
        rules_errored = 0

        try:
            grouped = await load_active_rules_grouped_by_ticker(session)

            for ticker, rules in grouped.items():
                # Fetch market data & signals for this ticker
                market_data = await market_data_repository.get_latest_market_data(
                    ticker
                )
                signals = await market_data_repository.get_latest_signals(ticker)

                # Freshness check
                fresh, reason = DataFreshnessValidator.validate_freshness(
                    market_data,
                    signals,
                    monitoring_settings.max_staleness_hours,
                )
                if not fresh:
                    rules_skipped += len(rules)
                    logger.warning(
                        "Skipping ticker %s (%d rules): %s",
                        ticker,
                        len(rules),
                        reason,
                    )
                    continue

                # market_data and signals are guaranteed non-None here
                assert market_data is not None
                assert signals is not None

                for rule in rules:
                    rules_evaluated += 1
                    try:
                        # Parse stored JSON params into typed schema
                        rule_params = _rule_params_adapter.validate_python(
                            rule.parameters
                        )

                        # Fetch previous state for stateful evaluators
                        prev_state = await state_repository.get_state(session, rule.id)

                        # Evaluate
                        result = evaluate_rule(
                            rule_params, market_data, signals, prev_state
                        )

                        if result.error:
                            rules_errored += 1
                            logger.warning(
                                "Rule %s (%s) errored: %s",
                                rule.id,
                                rule.name,
                                result.error_message,
                            )

                        if result.triggered:
                            # Cooldown check
                            is_dup = await AlertDeduplicationService.is_duplicate(
                                session, rule
                            )
                            if not is_dup:
                                alert = await AlertService.create_alert(
                                    session, rule, result, run_id=run.id
                                )
                                if alert is not None:
                                    rules_triggered += 1
                                    logger.info(
                                        "Alert created: rule=%s ticker=%s",
                                        rule.id,
                                        rule.ticker,
                                    )
                            else:
                                logger.debug(
                                    "Alert suppressed (cooldown): rule=%s",
                                    rule.id,
                                )

                        # Upsert state
                        consecutive = (
                            (prev_state.consecutive_triggers if prev_state else 0)
                            + (1 if result.triggered else 0)
                            if result.triggered
                            else 0
                        )
                        state_data = (
                            prev_state.state_data.copy()
                            if prev_state and prev_state.state_data
                            else {}
                        )
                        # For MA cross evaluator, persist crossover state
                        if "currently_above_sma" in result.evidence:
                            state_data["price_above_sma"] = result.evidence[
                                "currently_above_sma"
                            ]

                        await state_repository.upsert_state(
                            session,
                            rule.id,
                            last_value=result.current_value,
                            last_threshold_value=result.threshold_value,
                            last_triggered=result.triggered,
                            consecutive_triggers=consecutive,
                            state_data=state_data,
                        )

                    except Exception:
                        rules_errored += 1
                        logger.exception("Unexpected error evaluating rule %s", rule.id)

            # ── Finalise run ───────────────────────────────────────
            run.status = "completed"
            run.finished_at = datetime.now(tz=UTC)
            run.rules_evaluated = rules_evaluated
            run.rules_triggered = rules_triggered
            run.rules_skipped = rules_skipped
            run.rules_errored = rules_errored

            logger.info(
                "Monitoring cycle completed: evaluated=%d triggered=%d "
                "skipped=%d errored=%d",
                rules_evaluated,
                rules_triggered,
                rules_skipped,
                rules_errored,
            )

        except Exception as exc:
            run.status = "failed"
            run.finished_at = datetime.now(tz=UTC)
            run.rules_evaluated = rules_evaluated
            run.rules_triggered = rules_triggered
            run.rules_skipped = rules_skipped
            run.rules_errored = rules_errored
            run.error_message = str(exc)
            logger.exception("Monitoring cycle failed")
