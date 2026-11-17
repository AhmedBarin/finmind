"""The five read-only Stock Q&A tools.

Each tool reads PostgreSQL through the existing technical/market-data
repositories and returns stored values unchanged. None of them calculates an
indicator, a change, or a score.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.explanation.snapshots import json_value, snapshot_summary
from app.explanation.stock_qa import glossary
from app.explanation.stock_qa.schemas import PricePeriod, ToolResult
from app.market_data.repository import get_latest_stock_price, get_stock_price_history
from app.technical_analysis import repository as technical_repository
from app.technical_analysis.models import TechnicalSnapshot

PERIOD_DAYS: dict[str, int] = {"1w": 7, "1m": 31, "3m": 92, "6m": 183, "1y": 366}
SNAPSHOT_HISTORY_LIMIT = 60
PRICE_HISTORY_LIMIT = 260


def _snapshot_detail(snapshot: TechnicalSnapshot) -> dict[str, Any]:
    data = snapshot_summary(snapshot)
    data["indicators"] = dict(snapshot.indicators or {})
    data["scores"] = dict(snapshot.scores or {})
    return data


class StockQATools:
    """Read-only tool set bound to one request's database session."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def _snapshot(self, ticker: str, on: date | None) -> TechnicalSnapshot | None:
        if on is None:
            return await technical_repository.get_latest_snapshot(self._session, ticker)
        return await technical_repository.get_snapshot_by_date(self._session, ticker, on)

    async def get_technical_snapshot(self, ticker: str, on: date | None = None) -> ToolResult:
        snapshot = await self._snapshot(ticker, on)
        if snapshot is None:
            return ToolResult(
                tool="get_technical_snapshot",
                ticker=ticker,
                found=False,
                data={"requested_date": json_value(on)},
            )
        return ToolResult(
            tool="get_technical_snapshot",
            ticker=ticker,
            data_date=snapshot.date,
            data=_snapshot_detail(snapshot),
        )

    async def get_snapshot_history(
        self, ticker: str, start: date | None, end: date | None
    ) -> ToolResult:
        snapshots = await technical_repository.get_snapshot_history(
            self._session,
            ticker,
            start_date=start,
            end_date=end,
            limit=SNAPSHOT_HISTORY_LIMIT,
        )
        return ToolResult(
            tool="get_snapshot_history",
            ticker=ticker,
            data_date=snapshots[0].date if snapshots else None,
            found=bool(snapshots),
            data={
                "from": json_value(start),
                "to": json_value(end),
                "snapshots": [snapshot_summary(s) for s in snapshots],
            },
        )

    async def get_price_history(
        self, ticker: str, period: PricePeriod, end: date | None = None
    ) -> ToolResult:
        if end is None:
            latest = await get_latest_stock_price(self._session, ticker)
            end = latest.date if latest is not None else None
        if end is None:
            return ToolResult(
                tool="get_price_history",
                ticker=ticker,
                found=False,
                data={"period": period, "prices": []},
            )
        start = end - timedelta(days=PERIOD_DAYS[period])
        rows = await get_stock_price_history(
            self._session,
            ticker,
            start_date=start,
            end_date=end,
            limit=PRICE_HISTORY_LIMIT,
        )
        prices = [
            {
                "date": row.date.isoformat(),
                "close": json_value(row.raw_close),
                "adj_close": json_value(row.adj_close),
                "volume": row.volume,
            }
            for row in rows
        ]
        return ToolResult(
            tool="get_price_history",
            ticker=ticker,
            data_date=rows[-1].date if rows else None,
            found=bool(rows),
            data={"period": period, "from": start.isoformat(), "to": end.isoformat(), "prices": prices},
        )

    async def compare_snapshots(self, tickers: list[str], on: date | None = None) -> ToolResult:
        rows: list[dict[str, Any]] = []
        missing: list[str] = []
        for ticker in tickers:
            snapshot = await self._snapshot(ticker, on)
            if snapshot is None:
                missing.append(ticker)
            else:
                rows.append(snapshot_summary(snapshot))
        return ToolResult(
            tool="compare_snapshots",
            found=bool(rows),
            data={"requested_date": json_value(on), "snapshots": rows, "missing": missing},
        )

    async def get_indicator_glossary(self, name: str) -> ToolResult:
        entry = glossary.lookup(name)
        return ToolResult(
            tool="get_indicator_glossary",
            found=entry is not None,
            data={"key": name, **(dict(entry) if entry else {})},
        )
