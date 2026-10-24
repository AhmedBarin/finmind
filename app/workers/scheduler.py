from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from importlib import import_module


scheduler = AsyncIOScheduler(timezone="Africa/Cairo")


def start_scheduler() -> None:
    if scheduler.running:
        return

    scrape_mubasher = getattr(
        import_module("app.news.sources.mubasher"), "main"
    )

    scheduler.add_job(
        scrape_mubasher,
        trigger=CronTrigger(hour=19, minute=0),
        id="mubasher_daily",
        max_instances=1,
        coalesce=True,
        replace_existing=True,
    )

    scheduler.start()
    print("Mubasher scraper scheduled daily at 19:00 Cairo time.")


def stop_scheduler() -> None:
    if scheduler.running:
        scheduler.shutdown(wait=False)