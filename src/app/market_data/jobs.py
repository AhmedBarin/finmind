"""Backfill and recurring market-data ingestion jobs."""

from __future__ import annotations

import logging
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.market_data.fetcher import (
    EodhdFetcher,
    FallbackPriceFetcher,
    PriceFetcher,
    YahooFinanceFetcher,
)
from app.market_data.ingestion import IngestionReport, ingest_price_history
from app.market_data.repository import get_latest_stock_price
from app.technical_analysis.repository import get_snapshot_history
from app.technical_analysis.snapshot_service import calculate_and_persist_snapshot


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TickerJobResult:
    ticker: str
    ingestion: IngestionReport | None
    error: str | None = None


async def run_market_data_job(
    session_factory: async_sessionmaker[AsyncSession],
    tickers: Sequence[str],
    *,
    period: str,
    fetcher: PriceFetcher | None = None,
) -> tuple[TickerJobResult, ...]:
    """Fetch and persist each ticker independently.

    Database errors roll back only that ticker. A changed row triggers snapshot
    calculation for existing snapshot dates from the earliest changed date
    onward, plus the newest available price date. Initial full-history loads
    therefore create the current snapshot without quadratic historical work.
    """
    if period not in {"max", "1mo"}:
        raise ValueError("period must be 'max' for backfill or '1mo' for daily runs")

    selected_fetcher = fetcher or FallbackPriceFetcher(
        YahooFinanceFetcher(), EodhdFetcher()
    )
    results: list[TickerJobResult] = []
    normalized_tickers = tuple(dict.fromkeys(t.strip().upper() for t in tickers))
    if any(not ticker for ticker in normalized_tickers):
        raise ValueError("tickers must not contain empty values")

    for ticker in normalized_tickers:
        try:
            history = await selected_fetcher.fetch(ticker, period=period)
            # The provider may return a canonical symbol (for example .CA).
            ticker_key = history.ticker.strip().upper()
            async with session_factory() as session, session.begin():
                report = await ingest_price_history(session, history)
                if report.changed_dates:
                    await _recalculate_affected_snapshots(
                        session,
                        ticker_key,
                        min(report.changed_dates),
                    )
            results.append(TickerJobResult(ticker_key, report))
            logger.info(
                "Market-data ingestion ticker=%s source=%s inserted=%d updated=%d unchanged=%d",
                ticker_key,
                report.source,
                report.inserted,
                report.updated,
                report.unchanged,
            )
        except Exception as exc:
            logger.exception("Market-data ingestion failed for %s", ticker)
            results.append(TickerJobResult(ticker, None, str(exc)))

    return tuple(results)


async def run_market_data_backfill(
    session_factory: async_sessionmaker[AsyncSession],
    tickers: Sequence[str],
    *,
    fetcher: PriceFetcher | None = None,
) -> tuple[TickerJobResult, ...]:
    """Load maximum available provider history for each ticker."""
    return await run_market_data_job(
        session_factory,
        tickers,
        period="max",
        fetcher=fetcher,
    )


async def run_daily_market_data_ingestion(
    session_factory: async_sessionmaker[AsyncSession],
    tickers: Sequence[str],
    *,
    fetcher: PriceFetcher | None = None,
) -> tuple[TickerJobResult, ...]:
    """Fetch the latest month for daily insert/correction detection."""
    return await run_market_data_job(
        session_factory,
        tickers,
        period="1mo",
        fetcher=fetcher,
    )


async def _recalculate_affected_snapshots(
    session: AsyncSession,
    ticker: str,
    earliest_changed_date: date,
) -> None:
    latest_price = await get_latest_stock_price(session, ticker)
    if latest_price is None:
        return

    existing_snapshots = await get_snapshot_history(
        session,
        ticker,
        start_date=earliest_changed_date,
        end_date=latest_price.date,
    )
    snapshot_dates = {snapshot.date for snapshot in existing_snapshots}
    snapshot_dates.add(latest_price.date)

    for snapshot_date in sorted(snapshot_dates):
        await calculate_and_persist_snapshot(
            session,
            ticker,
            snapshot_date,
        )
