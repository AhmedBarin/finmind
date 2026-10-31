import logging
from datetime import datetime
from zoneinfo import ZoneInfo

from apscheduler.schedulers.asyncio import AsyncIOScheduler

from app.db.session import SessionLocal
from app.news.service import NewsService
from app.news.sources.registry import create_default_registry


logger = logging.getLogger(__name__)
CAIRO_TZ = ZoneInfo("Africa/Cairo")
scheduler = AsyncIOScheduler(timezone=CAIRO_TZ)


async def run_daily_news_ingestion() -> None:
    now = datetime.now(CAIRO_TZ)
    since = now.replace(hour=0, minute=0, second=0, microsecond=0)

    registry = create_default_registry()
    service = NewsService(
        session_factory=SessionLocal,
        registry=registry,
    )

    for source in registry.all():
        try:
            summary = await service.ingest_source(
                source.source_key,
                since=since,
            )
            logger.info(
                "News ingestion finished for %s: fetched=%d saved=%d duplicates=%d",
                summary.source_key,
                summary.fetched,
                summary.saved,
                summary.duplicates,
            )
        except Exception:
            logger.exception(
                "News ingestion failed for source %s",
                source.source_key,
            )


def start_scheduler() -> None:
    if scheduler.running:
        return

    scheduler.add_job(
        run_daily_news_ingestion,
        trigger="cron",
        hour=19,
        minute=0,
        timezone=CAIRO_TZ,
        id="daily_news_ingestion",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
    )
    scheduler.start()
    logger.info("News ingestion scheduled daily at 19:00 Cairo time.")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)