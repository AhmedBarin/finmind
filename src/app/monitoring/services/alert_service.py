"""Alert creation service – persists alerts with duplicate-safe handling."""

from __future__ import annotations

import logging
from uuid import UUID

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.monitoring.models.alert import Alert
from app.monitoring.models.monitoring_rule import MonitoringRule
from app.monitoring.schemas.market_data import EvaluationResult

logger = logging.getLogger(__name__)


class AlertService:
    """Create alert records, handling unique-constraint conflicts gracefully."""

    @staticmethod
    async def create_alert(
        session: AsyncSession,
        rule: MonitoringRule,
        eval_result: EvaluationResult,
        run_id: UUID | None = None,
    ) -> Alert | None:
        """Persist an alert for *rule* based on *eval_result*.

        If the ``uq_alert_daily`` unique constraint is violated the
        savepoint is rolled back and ``None`` is returned (suppressed
        duplicate).
        """
        alert = Alert(
            rule_id=rule.id,
            user_id=rule.user_id,
            ticker=rule.ticker,
            alert_type=rule.rule_type,
            severity=_infer_severity(eval_result),
            reason=eval_result.reason,
            evidence=eval_result.evidence,
            current_value=eval_result.current_value,
            threshold_value=eval_result.threshold_value,
            run_id=run_id,
        )

        savepoint = await session.begin_nested()
        try:
            session.add(alert)
            await session.flush()
            return alert
        except IntegrityError:
            await savepoint.rollback()
            logger.info(
                "Duplicate alert suppressed for rule %s / ticker %s",
                rule.id,
                rule.ticker,
            )
            return None


def _infer_severity(eval_result: EvaluationResult) -> str:
    """Simple heuristic: map evaluation outcome to a severity string."""
    if eval_result.error:
        return "WARNING"
    if (
        eval_result.current_value is not None
        and eval_result.threshold_value is not None
    ):
        ratio = abs(eval_result.current_value) / max(
            abs(eval_result.threshold_value), 1e-9
        )
        if ratio >= 1.5:
            return "CRITICAL"
    return "INFO"
