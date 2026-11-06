"""Tests for Step 9 — APScheduler monitoring scheduler."""

from __future__ import annotations

import asyncio
from zoneinfo import ZoneInfo

import pytest
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

import app.monitoring.scheduler as sched_mod
from app.monitoring.scheduler import (
    start_monitoring_scheduler,
    stop_monitoring_scheduler,
)

CAIRO_TZ = ZoneInfo("Africa/Cairo")


class TestMonitoringScheduler:
    """Verify the monitoring scheduler initialises and configures correctly."""

    def setup_method(self) -> None:
        """Create a fresh AsyncIOScheduler before each test."""
        self.sched = AsyncIOScheduler(timezone=CAIRO_TZ)
        sched_mod.scheduler = self.sched

    def teardown_method(self) -> None:
        """Clean up scheduler after each test."""
        if self.sched.running:
            self.sched.shutdown(wait=False)

    @pytest.mark.asyncio
    async def test_start_creates_job(self) -> None:
        start_monitoring_scheduler()
        assert self.sched.running

        job = self.sched.get_job("monitoring_cycle")
        assert job is not None

        stop_monitoring_scheduler()
        await asyncio.sleep(0.05)
        assert not self.sched.running

    @pytest.mark.asyncio
    async def test_start_is_idempotent(self) -> None:
        start_monitoring_scheduler()
        start_monitoring_scheduler()  # should not raise or duplicate
        assert self.sched.running

        jobs = self.sched.get_jobs()
        monitoring_jobs = [j for j in jobs if j.id == "monitoring_cycle"]
        assert len(monitoring_jobs) == 1

        stop_monitoring_scheduler()
        await asyncio.sleep(0.05)
        assert not self.sched.running

    @pytest.mark.asyncio
    async def test_job_has_correct_cron_trigger(self) -> None:
        start_monitoring_scheduler()
        job = self.sched.get_job("monitoring_cycle")
        assert job is not None

        trigger = job.trigger
        assert isinstance(trigger, CronTrigger)

        stop_monitoring_scheduler()
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_job_trigger_fields(self) -> None:
        start_monitoring_scheduler()
        job = self.sched.get_job("monitoring_cycle")
        assert job is not None

        trigger = job.trigger
        assert isinstance(trigger, CronTrigger)

        fields = {f.name: str(f) for f in trigger.fields}
        assert fields["day_of_week"] == "sun,mon,tue,wed,thu"
        assert fields["hour"] == "15"
        assert fields["minute"] == "30"

        stop_monitoring_scheduler()
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_next_run_time_is_cairo_tz(self) -> None:
        start_monitoring_scheduler()
        job = self.sched.get_job("monitoring_cycle")
        assert job is not None
        assert job.next_run_time is not None

        # next_run_time should be timezone-aware
        assert job.next_run_time.tzinfo is not None
        cairo_next = job.next_run_time.astimezone(CAIRO_TZ)
        assert cairo_next.hour == 15
        assert cairo_next.minute == 30
        # Should be on a trading day (Sun=6, Mon=0, Tue=1, Wed=2, Thu=3)
        assert cairo_next.weekday() in {6, 0, 1, 2, 3}

        stop_monitoring_scheduler()
        await asyncio.sleep(0.05)

    @pytest.mark.asyncio
    async def test_stop_shuts_down_cleanly(self) -> None:
        start_monitoring_scheduler()
        assert self.sched.running

        stop_monitoring_scheduler()
        await asyncio.sleep(0.05)
        assert not self.sched.running

    def test_stop_when_not_running_is_safe(self) -> None:
        # Should not raise even if scheduler was never started
        stop_monitoring_scheduler()
        assert not self.sched.running
