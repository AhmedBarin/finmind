import asyncio
from datetime import datetime
from zoneinfo import ZoneInfo

from app.db.session import SessionLocal, engine
from app.news.service import NewsService
from app.news.sources.registry import create_default_registry


CAIRO_TZ = ZoneInfo("Africa/Cairo")


async def main() -> None:
    now = datetime.now(CAIRO_TZ)
    since = now.replace(hour=0, minute=0, second=0, microsecond=0)

    service = NewsService(
        session_factory=SessionLocal,
        registry=create_default_registry(),
    )

    try:
        summary = await service.ingest_source("mubasher", since=since)
        print("\n=== Ingestion summary ===")
        print(f"Source: {summary.source_key}")
        print(f"Fetched: {summary.fetched}")
        print(f"Saved: {summary.saved}")
        print(f"Duplicates: {summary.duplicates}")
        print(f"Failed: {summary.failed}")
        print(f"Run ID: {summary.run_id}")
        
    finally:
        await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())