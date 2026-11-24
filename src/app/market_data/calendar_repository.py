"""Persistence for explicitly verified EGX calendar data.

Stock Q&A tools call only the read path. The write helper is intended for a
separate operator/import process that has checked official EGX announcements.
"""

from __future__ import annotations

from datetime import date
from typing import Iterable

from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.calendar import (
    OfficialEGXHoliday,
    VerifiedEGXCalendar,
    get_verified_egx_calendar,
)
from app.market_data.models import EGXCalendarCoverage, EGXMarketHoliday


async def record_verified_egx_calendar(
    session: AsyncSession,
    *,
    coverage_start: date,
    verified_through: date,
    verification_reference_url: str,
    holidays: Iterable[OfficialEGXHoliday],
) -> None:
    """Store a verified interval and its officially announced closure dates.

    The caller must verify that every EGX closure inside the interval is
    represented. This method validates that references point to the official
    EGX HTTPS domain and leaves commit/rollback to the caller.
    """
    supplied_holidays = tuple(holidays)
    VerifiedEGXCalendar(
        coverage_start=coverage_start,
        verified_through=verified_through,
        verification_reference_urls=(verification_reference_url,),
        holidays=supplied_holidays,
    )
    statement = pg_insert(EGXCalendarCoverage).values(
        coverage_start=coverage_start,
        verified_through=verified_through,
        verification_reference_url=verification_reference_url,
    )
    statement = statement.on_conflict_do_update(
        constraint="uq_egx_calendar_coverage_start",
        set_={
            "verified_through": func.greatest(
                EGXCalendarCoverage.verified_through,
                statement.excluded.verified_through,
            ),
            "verification_reference_url": statement.excluded.verification_reference_url,
            "verified_at": func.now(),
        },
        where=statement.excluded.verified_through
        >= EGXCalendarCoverage.verified_through,
    )
    await session.execute(statement)

    for holiday in supplied_holidays:
        holiday_statement = pg_insert(EGXMarketHoliday).values(
            holiday_date=holiday.holiday_date,
            holiday_name=holiday.holiday_name,
            announcement_url=holiday.announcement_url,
        )
        holiday_statement = holiday_statement.on_conflict_do_update(
            index_elements=[EGXMarketHoliday.holiday_date],
            set_={
                "holiday_name": holiday_statement.excluded.holiday_name,
                "announcement_url": holiday_statement.excluded.announcement_url,
            },
        )
        await session.execute(holiday_statement)


async def read_verified_egx_calendar(
    session: AsyncSession,
    start_date: date,
    end_date: date,
) -> VerifiedEGXCalendar | None:
    """Public repository entry point used by freshness tools."""
    return await get_verified_egx_calendar(session, start_date, end_date)
