import asyncio
import argparse
from datetime import datetime
from zoneinfo import ZoneInfo
from datetime import datetime, timedelta
from app.db.session import SessionLocal, engine
from app.news.service import NewsService
from app.news.sources.registry import create_default_registry
from app.core.dependencies import get_news_retrieval_indexer


CAIRO_TZ = ZoneInfo("Africa/Cairo")


async def main(source_key: str | None = None) -> None:
    now = datetime.now(CAIRO_TZ)
    since = now - timedelta(days=3)

    registry = create_default_registry()
    service = NewsService(
        session_factory=SessionLocal,
        registry=registry,
        retrieval_indexer=get_news_retrieval_indexer(),
    )

    try:
        sources = registry.all()
        if source_key:
            sources = (registry.get(source_key),)

        for source in sources:
            summary = await service.ingest_source(source.source_key, since=since)
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
    parser = argparse.ArgumentParser(description="Run FinMind news ingestion")
    parser.add_argument(
        "--source",
        choices=("mubasher", "daily_news_egypt"),
        help="Run one source only; omit it to run all registered sources.",
    )
    args = parser.parse_args()
    asyncio.run(main(args.source))
