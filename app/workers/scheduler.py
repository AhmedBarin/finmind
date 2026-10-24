from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger

from app.news.sources.mubasher import main as scrape_mubasher


scheduler = AsyncIOScheduler(timezone="Africa/Cairo")


def start_scheduler() -> None:
    if scheduler.running:
        return

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