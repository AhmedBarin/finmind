"""Admin router – trigger monitoring runs and inspect history."""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, Query
from sqlalchemy import select

from app.db.session import SessionLocal
from app.monitoring.models.monitoring_run import MonitoringRun
from app.monitoring.services.job_runner import run_monitoring_cycle

router = APIRouter(prefix="/admin", tags=["admin"])


@router.post("/run", status_code=202)
async def trigger_run() -> dict[str, str]:
    """Trigger a monitoring cycle in the background."""
    asyncio.create_task(run_monitoring_cycle(SessionLocal))
    return {"detail": "Monitoring cycle triggered"}


@router.get("/runs")
async def list_runs(
    limit: int = Query(default=10, ge=1, le=100),
) -> list[dict]:
    """List recent monitoring runs."""
    async with SessionLocal() as session:
        stmt = (
            select(MonitoringRun).order_by(MonitoringRun.started_at.desc()).limit(limit)
        )
        result = await session.execute(stmt)
        runs = result.scalars().all()
        return [
            {
                "id": str(r.id),
                "started_at": r.started_at.isoformat() if r.started_at else None,
                "finished_at": r.finished_at.isoformat() if r.finished_at else None,
                "status": r.status,
                "rules_evaluated": r.rules_evaluated,
                "rules_triggered": r.rules_triggered,
                "rules_skipped": r.rules_skipped,
                "rules_errored": r.rules_errored,
                "error_message": r.error_message,
            }
            for r in runs
        ]
