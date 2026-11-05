"""Alert deduplication service – cooldown-based duplicate detection."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.monitoring.models.alert import Alert
from app.monitoring.models.monitoring_rule import MonitoringRule


class AlertDeduplicationService:
    """Check whether an alert for a given rule was already fired recently."""

    @staticmethod
    async def is_duplicate(
        session: AsyncSession,
        rule: MonitoringRule,
    ) -> bool:
        """Return ``True`` if an alert for *rule* exists within the cooldown window."""
        cutoff = datetime.now(tz=UTC) - timedelta(minutes=rule.cooldown_minutes)
        stmt = (
            select(Alert.id)
            .where(
                Alert.rule_id == rule.id,
                Alert.created_at >= cutoff,
            )
            .limit(1)
        )
        result = await session.execute(stmt)
        return result.scalar_one_or_none() is not None
