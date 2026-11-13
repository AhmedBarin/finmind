"""Daily Cairo-time scheduler for market-data refreshes."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.db.session import SessionLocal
from app.market_data.fetcher import (
    EodhdFetcher,
    FallbackPriceFetcher,
    PriceFetcher,
    YahooFinanceFetcher,
)
from app.market_data.jobs import run_daily_market_data_ingestion


logger = logging.getLogger(__name__)
CAIRO_TZ = ZoneInfo("Africa/Cairo")
scheduler = AsyncIOScheduler(timezone=CAIRO_TZ)


def start_market_data_scheduler(
    tickers: Sequence[str],
    *,
    session_factory: async_sessionmaker[AsyncSession] = SessionLocal,
    fetcher: PriceFetcher | None = None,
) -> None:
    """Schedule the daily fetch at 15:30 Cairo time, including holidays.

    Yahoo returns no new rows on non-trading days; that is treated as a normal
    empty result by the fetcher. Holiday-specific stale checks remain in the
    market-data quality calendar.
    """
    if not tickers:
        raise ValueError("at least one ticker is required to start the scheduler")
    if scheduler.running:
        return

    scheduler.add_job(
        run_daily_market_data_ingestion,
        trigger="cron",
        hour=15,
        minute=30,
        timezone=CAIRO_TZ,
        id="market_data_daily_ingestion",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        args=[session_factory, tuple(tickers)],
        kwargs={
            "fetcher": fetcher
            or FallbackPriceFetcher(YahooFinanceFetcher(), EodhdFetcher())
        },
    )
    scheduler.start()
    logger.info("Market-data ingestion scheduled daily at 15:30 Cairo time.")


def stop_market_data_scheduler() -> None:
    """Stop the scheduler if it is running."""
    if scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Market-data scheduler stopped.")
