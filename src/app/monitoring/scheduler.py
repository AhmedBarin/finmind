"""APScheduler background hook for the monitoring service.

Schedules ``run_monitoring_cycle`` to run on EGX trading days
(Sunday–Thursday) at 15:30 Cairo time — shortly after market close.
"""

from __future__ import annotations

import logging
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db.session import SessionLocal
from app.monitoring.services.job_runner import run_monitoring_cycle

logger = logging.getLogger(__name__)
CAIRO_TZ = ZoneInfo("Africa/Cairo")

scheduler = AsyncIOScheduler(timezone=CAIRO_TZ)


def start_monitoring_scheduler() -> None:
    """Start the monitoring scheduler if not already running."""
    if scheduler.running:
        return

    scheduler.add_job(
        run_monitoring_cycle,
        trigger="cron",
        day_of_week="sun,mon,tue,wed,thu",
        hour=15,
        minute=30,
        timezone=CAIRO_TZ,
        id="monitoring_cycle",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        args=[SessionLocal],
    )
    scheduler.start()
    logger.info("Monitoring scheduler started — Sun-Thu at 15:30 Cairo time.")


def stop_monitoring_scheduler() -> None:
    """Stop the monitoring scheduler cleanly."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Monitoring scheduler stopped.")
