"""Rules router – CRUD endpoints for monitoring rules."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import func, select

from app.db.session import SessionLocal
from app.monitoring.dependencies import get_current_user_id
from app.monitoring.models.monitoring_rule import MonitoringRule
from app.monitoring.repositories import rule_repository
from app.monitoring.schemas.rules import (
    RuleCreateRequest,
    RuleResponse,
    RuleUpdateRequest,
)

router = APIRouter(prefix="/rules", tags=["rules"])

MAX_RULES_PER_USER = 50


@router.post("", response_model=RuleResponse, status_code=201)
async def create_rule(
    req: RuleCreateRequest,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
) -> RuleResponse:
    """Create a new monitoring rule (max 50 per user)."""
    async with SessionLocal() as session, session.begin():
        # Enforce per-user limit
        count_result = await session.execute(
            select(func.count())
            .select_from(MonitoringRule)
            .where(
                MonitoringRule.user_id == user_id,
                MonitoringRule.is_active.is_(True),
            )
        )
        current_count = count_result.scalar_one()
        if current_count >= MAX_RULES_PER_USER:
            raise HTTPException(
                status_code=409,
                detail=f"Maximum of {MAX_RULES_PER_USER} active rules per user exceeded",
            )

        rule = await rule_repository.create_rule(session, user_id, req)
        return RuleResponse.model_validate(rule)


@router.get("", response_model=list[RuleResponse])
async def list_rules(
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    ticker: str | None = Query(default=None),
) -> list[RuleResponse]:
    """List the caller's active monitoring rules."""
    async with SessionLocal() as session:
        stmt = select(MonitoringRule).where(
            MonitoringRule.user_id == user_id,
            MonitoringRule.is_active.is_(True),
        )
        if ticker is not None:
            stmt = stmt.where(MonitoringRule.ticker == ticker)
        stmt = stmt.order_by(MonitoringRule.created_at.desc())
        result = await session.execute(stmt)
        rules = result.scalars().all()
        return [RuleResponse.model_validate(r) for r in rules]


@router.get("/{rule_id}", response_model=RuleResponse)
async def get_rule(
    rule_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
) -> RuleResponse:
    """Get a single rule by ID (must be owned by caller)."""
    async with SessionLocal() as session:
        rule = await rule_repository.get_rule(session, rule_id, user_id)
        if rule is None or not rule.is_active:
            raise HTTPException(status_code=404, detail="Rule not found")
        return RuleResponse.model_validate(rule)


@router.patch("/{rule_id}", response_model=RuleResponse)
async def update_rule(
    rule_id: UUID,
    req: RuleUpdateRequest,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
) -> RuleResponse:
    """Partially update a rule."""
    async with SessionLocal() as session, session.begin():
        rule = await rule_repository.update_rule(session, rule_id, user_id, req)
        if rule is None:
            raise HTTPException(status_code=404, detail="Rule not found")
        return RuleResponse.model_validate(rule)


@router.delete("/{rule_id}", status_code=204)
async def delete_rule(
    rule_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
) -> None:
    """Soft-delete a rule (set is_active=False)."""
    async with SessionLocal() as session, session.begin():
        deleted = await rule_repository.soft_delete_rule(session, rule_id, user_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="Rule not found")
