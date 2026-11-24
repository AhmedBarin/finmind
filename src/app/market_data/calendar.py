"""Read-only helpers for the explicitly verified EGX trading calendar."""

from __future__ import annotations

from datetime import date, timedelta
from urllib.parse import urlparse

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.config import EGX_TRADING_WEEKDAYS
from app.market_data.models import EGXCalendarCoverage, EGXMarketHoliday


class OfficialEGXHoliday(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    holiday_date: date
    holiday_name: str = Field(min_length=1, max_length=200)
    announcement_url: str = Field(min_length=1, max_length=2048)

    @field_validator("announcement_url")
    @classmethod
    def require_egx_announcement(cls, value: str) -> str:
        parsed = urlparse(value)
        host = (parsed.hostname or "").lower()
        if parsed.scheme != "https" or not (
            host == "egx.com.eg" or host.endswith(".egx.com.eg")
        ):
            raise ValueError("holiday reference must be an official EGX HTTPS URL")
        return value


class VerifiedEGXCalendar(BaseModel):
    """A complete, source-verified interval and its announced closure dates."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    coverage_start: date
    verified_through: date
    verification_reference_urls: tuple[str, ...] = Field(min_length=1, max_length=20)
    holidays: tuple[OfficialEGXHoliday, ...] = ()

    @field_validator("verification_reference_urls")
    @classmethod
    def require_official_verification_references(cls, values: tuple[str, ...]) -> tuple[str, ...]:
        for value in values:
            parsed = urlparse(value)
            host = (parsed.hostname or "").lower()
            if parsed.scheme != "https" or not (
                host == "egx.com.eg" or host.endswith(".egx.com.eg")
            ):
                raise ValueError("coverage references must be official EGX HTTPS URLs")
        return values

    @model_validator(mode="after")
    def validate_interval(self) -> "VerifiedEGXCalendar":
        if self.verified_through < self.coverage_start:
            raise ValueError("verified_through must not precede coverage_start")
        if any(
            item.holiday_date < self.coverage_start
            or item.holiday_date > self.verified_through
            for item in self.holidays
        ):
            raise ValueError("holiday date falls outside verified calendar coverage")
        return self


async def get_verified_egx_calendar(
    session: AsyncSession,
    start_date: date,
    end_date: date,
) -> VerifiedEGXCalendar | None:
    """Load a continuous, verified interval; gaps are reported as unavailable.

    Coverage records are explicit attestations that all official EGX closures
    were entered for the interval. An absent holiday row is only treated as an
    open session inside such verified coverage.
    """
    if end_date < start_date:
        raise ValueError("end_date must not precede start_date")

    coverage_result = await session.scalars(
        select(EGXCalendarCoverage)
        .where(
            EGXCalendarCoverage.coverage_start <= end_date,
            EGXCalendarCoverage.verified_through >= start_date,
        )
        .order_by(EGXCalendarCoverage.coverage_start.asc())
    )
    coverage_rows = list(coverage_result.all())
    cursor = start_date
    used: list[EGXCalendarCoverage] = []
    for row in coverage_rows:
        row_end = row.verified_through
        if row.coverage_start > cursor:
            break
        if row_end < cursor:
            continue
        used.append(row)
        cursor = row_end + timedelta(days=1)
        if cursor > end_date:
            break
    if cursor <= end_date:
        return None

    holiday_result = await session.scalars(
        select(EGXMarketHoliday).where(
            EGXMarketHoliday.holiday_date >= start_date,
            EGXMarketHoliday.holiday_date <= end_date,
        )
    )
    holidays = tuple(
        OfficialEGXHoliday(
            holiday_date=row.holiday_date,
            holiday_name=row.holiday_name,
            announcement_url=row.announcement_url,
        )
        for row in holiday_result.all()
    )
    return VerifiedEGXCalendar(
        coverage_start=start_date,
        verified_through=end_date,
        verification_reference_urls=tuple(
            dict.fromkeys(row.verification_reference_url for row in used)
        ),
        holidays=holidays,
    )


def count_egx_sessions(
    start_date: date,
    end_date: date,
    holidays: tuple[OfficialEGXHoliday, ...],
) -> int:
    """Count EGX sessions in an inclusive interval, excluding weekends/holidays."""
    if end_date < start_date:
        return 0
    closed_dates = {holiday.holiday_date for holiday in holidays}
    count = 0
    current = start_date
    while current <= end_date:
        if current.weekday() in EGX_TRADING_WEEKDAYS and current not in closed_dates:
            count += 1
        current += timedelta(days=1)
    return count
