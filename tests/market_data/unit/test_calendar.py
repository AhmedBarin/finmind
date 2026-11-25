from __future__ import annotations

from datetime import date
from unittest.mock import AsyncMock

import pytest
from pydantic import ValidationError

from app.market_data.calendar import (
    OfficialEGXHoliday,
    count_egx_sessions,
)
from app.market_data.calendar_repository import record_verified_egx_calendar


OFFICIAL_URL = "https://beta.egx.com.eg/en/media-center"


def test_egx_session_count_excludes_friday_saturday_and_official_holiday() -> None:
    monday = date(2026, 11, 23)
    holiday = OfficialEGXHoliday(
        holiday_date=monday,
        holiday_name="Official closure",
        announcement_url=OFFICIAL_URL,
    )

    sessions = count_egx_sessions(
        date(2026, 11, 19), date(2026, 11, 24), (holiday,)
    )

    # Thursday, Sunday, and Tuesday are sessions; Fri/Sat and Monday are closed.
    assert sessions == 3


def test_official_holiday_requires_official_https_egx_reference() -> None:
    with pytest.raises(ValidationError, match="official EGX HTTPS URL"):
        OfficialEGXHoliday(
            holiday_date=date(2026, 11, 23),
            holiday_name="Closure",
            announcement_url="https://example.com/egx-holiday",
        )


@pytest.mark.asyncio
async def test_calendar_writer_validates_coverage_and_persists_verified_holiday() -> None:
    session = AsyncMock()
    holiday = OfficialEGXHoliday(
        holiday_date=date(2026, 11, 23),
        holiday_name="Official closure",
        announcement_url=OFFICIAL_URL,
    )

    await record_verified_egx_calendar(
        session,
        coverage_start=date(2026, 1, 1),
        verified_through=date(2026, 11, 24),
        verification_reference_url=OFFICIAL_URL,
        holidays=(holiday,),
    )

    assert session.execute.await_count == 2


@pytest.mark.asyncio
async def test_calendar_writer_rejects_non_egx_coverage_reference_before_writing() -> None:
    session = AsyncMock()

    with pytest.raises(ValidationError, match="official EGX HTTPS URL"):
        await record_verified_egx_calendar(
            session,
            coverage_start=date(2026, 1, 1),
            verified_through=date(2026, 11, 24),
            verification_reference_url="https://example.com/calendar",
            holidays=(),
        )

    session.execute.assert_not_awaited()
