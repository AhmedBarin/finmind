"""Rule repository – CRUD operations for MonitoringRule."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.monitoring.models.monitoring_rule import MonitoringRule
from app.monitoring.schemas.rules import RuleCreateRequest, RuleUpdateRequest


async def load_active_rules_grouped_by_ticker(
    session: AsyncSession,
) -> dict[str, list[MonitoringRule]]:
    """Return active rules keyed by ticker symbol."""
    stmt = (
        select(MonitoringRule)
        .where(
            MonitoringRule.is_active.is_(True),
            MonitoringRule.deactivated_at.is_(None),
        )
        .order_by(MonitoringRule.ticker)
    )
    result = await session.execute(stmt)
    rules = result.scalars().all()

    grouped: dict[str, list[MonitoringRule]] = defaultdict(list)
    for rule in rules:
        grouped[rule.ticker].append(rule)
    return dict(grouped)


async def get_rule(
    session: AsyncSession,
    rule_id: UUID,
    user_id: UUID,
) -> MonitoringRule | None:
    """Fetch a single rule owned by *user_id*."""
    stmt = select(MonitoringRule).where(
        MonitoringRule.id == rule_id,
        MonitoringRule.user_id == user_id,
    )
    result = await session.execute(stmt)
    return result.scalar_one_or_none()


async def create_rule(
    session: AsyncSession,
    user_id: UUID,
    req: RuleCreateRequest,
) -> MonitoringRule:
    """Insert a new monitoring rule and flush to obtain server defaults."""
    rule = MonitoringRule(
        user_id=user_id,
        name=req.name,
        ticker=req.ticker,
        rule_type=req.parameters.rule_type.value,
        parameters=req.parameters.model_dump(),
        cooldown_minutes=req.cooldown_minutes,
    )
    session.add(rule)
    await session.flush()
    return rule


async def update_rule(
    session: AsyncSession,
    rule_id: UUID,
    user_id: UUID,
    req: RuleUpdateRequest,
) -> MonitoringRule | None:
    """Apply a partial update to an existing rule."""
    rule = await get_rule(session, rule_id, user_id)
    if rule is None:
        return None

    if req.name is not None:
        rule.name = req.name
    if req.parameters is not None:
        rule.rule_type = req.parameters.rule_type.value
        rule.parameters = req.parameters.model_dump()
    if req.is_active is not None:
        rule.is_active = req.is_active
        if not req.is_active:
            rule.deactivated_at = datetime.now(tz=UTC)
        else:
            rule.deactivated_at = None
    if req.cooldown_minutes is not None:
        rule.cooldown_minutes = req.cooldown_minutes

    await session.flush()
    return rule


async def soft_delete_rule(
    session: AsyncSession,
    rule_id: UUID,
    user_id: UUID,
) -> bool:
    """Soft-delete a rule by deactivating it. Returns ``True`` on success."""
    rule = await get_rule(session, rule_id, user_id)
    if rule is None:
        return False

    rule.is_active = False
    rule.deactivated_at = datetime.now(tz=UTC)
    await session.flush()
    return True
