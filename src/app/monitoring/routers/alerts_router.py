"""Alerts router – list and acknowledge alerts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select

from app.db.session import SessionLocal
from app.monitoring.dependencies import get_current_user_id
from app.monitoring.models.alert import Alert
from app.monitoring.schemas.alerts import AlertAcknowledgeResponse, AlertResponse

router = APIRouter(prefix="/alerts", tags=["alerts"])


@router.get("", response_model=list[AlertResponse])
async def list_alerts(
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    ticker: str | None = Query(default=None),
    unacknowledged_only: bool = Query(default=False),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
) -> list[AlertResponse]:
    """List alerts for the authenticated user with optional filters."""
    async with SessionLocal() as session:
        stmt = select(Alert).where(Alert.user_id == user_id)

        if ticker is not None:
            stmt = stmt.where(Alert.ticker == ticker)
        if unacknowledged_only:
            stmt = stmt.where(Alert.acknowledged_at.is_(None))

        stmt = stmt.order_by(Alert.created_at.desc()).limit(limit).offset(offset)
        result = await session.execute(stmt)
        alerts = result.scalars().all()
        return [AlertResponse.model_validate(a) for a in alerts]


@router.post(
    "/{alert_id}/acknowledge",
    response_model=AlertAcknowledgeResponse,
)
async def acknowledge_alert(
    alert_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
) -> AlertAcknowledgeResponse:
    """Mark an alert as acknowledged."""
    async with SessionLocal() as session, session.begin():
        stmt = select(Alert).where(
            Alert.id == alert_id,
            Alert.user_id == user_id,
        )
        result = await session.execute(stmt)
        alert = result.scalar_one_or_none()

        if alert is None:
            raise HTTPException(status_code=404, detail="Alert not found")

        if alert.acknowledged_at is not None:
            raise HTTPException(status_code=409, detail="Alert already acknowledged")

        alert.acknowledged_at = datetime.now(tz=UTC)
        await session.flush()
        return AlertAcknowledgeResponse.model_validate(alert)
