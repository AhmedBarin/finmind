"""State repository – get / upsert for MonitoringRuleState."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.monitoring.models.monitoring_rule_state import MonitoringRuleState


async def get_state(
    session: AsyncSession,
    rule_id: UUID,
) -> MonitoringRuleState | None:
    """Fetch the persisted state for a rule, or ``None``."""
    return await session.get(MonitoringRuleState, rule_id)


async def upsert_state(
    session: AsyncSession,
    rule_id: UUID,
    *,
    last_evaluated_at: datetime | None = None,
    last_value: float | None = None,
    last_threshold_value: float | None = None,
    last_triggered: bool | None = None,
    consecutive_triggers: int = 0,
    state_data: dict[str, Any] | None = None,
) -> MonitoringRuleState:
    """Insert or update the rule state using ``ON CONFLICT DO UPDATE``.

    This avoids a separate SELECT→INSERT/UPDATE round-trip and is safe
    under concurrent writers because the PK constraint acts as the lock.
    """
    now = last_evaluated_at or datetime.now(tz=UTC)
    data = state_data if state_data is not None else {}

    stmt = text("""
        INSERT INTO monitoring_rule_states (
            rule_id,
            last_evaluated_at,
            last_value,
            last_threshold_value,
            last_triggered,
            consecutive_triggers,
            state_data
        ) VALUES (
            :rule_id,
            :last_evaluated_at,
            :last_value,
            :last_threshold_value,
            :last_triggered,
            :consecutive_triggers,
            CAST(:state_data AS jsonb)
        )
        ON CONFLICT (rule_id) DO UPDATE SET
            last_evaluated_at    = EXCLUDED.last_evaluated_at,
            last_value           = EXCLUDED.last_value,
            last_threshold_value = EXCLUDED.last_threshold_value,
            last_triggered       = EXCLUDED.last_triggered,
            consecutive_triggers = EXCLUDED.consecutive_triggers,
            state_data           = EXCLUDED.state_data
        RETURNING rule_id
    """)

    import json

    await session.execute(
        stmt,
        {
            "rule_id": str(rule_id),
            "last_evaluated_at": now,
            "last_value": last_value,
            "last_threshold_value": last_threshold_value,
            "last_triggered": last_triggered,
            "consecutive_triggers": consecutive_triggers,
            "state_data": json.dumps(data),
        },
    )
    await session.flush()

    # Expire the ORM cache and re-fetch to return a proper mapped instance
    state = await session.get(MonitoringRuleState, rule_id)
    if state is not None:
        await session.refresh(state)
    return state  # type: ignore[return-value]
