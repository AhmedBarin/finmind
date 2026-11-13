"""Authenticated, read-only technical snapshot and price routes."""

from __future__ import annotations

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Path, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.repository import get_stock_price_history
from app.monitoring.dependencies import get_current_user_id
from app.technical_analysis.dependencies import get_technical_session
from app.technical_analysis.repository import (
    compare_snapshots,
    get_latest_snapshot,
    get_latest_valid_snapshot,
    get_snapshot_by_date,
    get_snapshot_history,
)
from app.technical_analysis.schemas import (
    StockPriceHistoryRead,
    TechnicalSnapshotComparisonRead,
    TechnicalSnapshotHistoryRead,
    TechnicalSnapshotRead,
)


router = APIRouter(
    prefix="/api/v1/technical",
    tags=["technical"],
    dependencies=[Depends(get_current_user_id)],
)

TickerPath = Annotated[
    str,
    Path(
        min_length=1,
        max_length=20,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9.-]{0,19}$",
    ),
]
SessionDep = Annotated[AsyncSession, Depends(get_technical_session)]


def _validate_date_range(from_date: date | None, to_date: date | None) -> None:
    if from_date is not None and to_date is not None and from_date > to_date:
        raise HTTPException(
            status_code=422,
            detail="from must be on or before to",
        )


@router.get("/{ticker}/snapshots/latest", response_model=TechnicalSnapshotRead)
async def read_latest_snapshot(
    ticker: TickerPath,
    session: SessionDep,
) -> TechnicalSnapshotRead:
    snapshot = await get_latest_snapshot(session, ticker)
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Technical snapshot not found")
    return TechnicalSnapshotRead.model_validate(snapshot)


@router.get(
    "/{ticker}/snapshots/latest-valid",
    response_model=TechnicalSnapshotRead,
)
async def read_latest_valid_snapshot(
    ticker: TickerPath,
    session: SessionDep,
) -> TechnicalSnapshotRead:
    snapshot = await get_latest_valid_snapshot(session, ticker)
    if snapshot is None:
        raise HTTPException(
            status_code=404,
            detail="No valid technical snapshot found",
        )
    return TechnicalSnapshotRead.model_validate(snapshot)


@router.get(
    "/{ticker}/snapshots/compare",
    response_model=TechnicalSnapshotComparisonRead,
)
async def read_snapshot_comparison(
    ticker: TickerPath,
    session: SessionDep,
    first_date: date = Query(alias="first"),
    second_date: date = Query(alias="second"),
    config_version: str | None = Query(default=None, min_length=1, max_length=50),
) -> TechnicalSnapshotComparisonRead:
    first, second = await compare_snapshots(
        session,
        ticker,
        first_date,
        second_date,
        config_version=config_version,
    )
    if first is None and second is None:
        raise HTTPException(status_code=404, detail="No snapshots found for either date")
    return TechnicalSnapshotComparisonRead(
        ticker=ticker.strip().upper(),
        first=first,
        second=second,
    )


@router.get(
    "/{ticker}/snapshots/{snapshot_date}",
    response_model=TechnicalSnapshotRead,
)
async def read_snapshot_by_date(
    ticker: TickerPath,
    snapshot_date: date,
    session: SessionDep,
    config_version: str | None = Query(default=None, min_length=1, max_length=50),
) -> TechnicalSnapshotRead:
    snapshot = await get_snapshot_by_date(
        session,
        ticker,
        snapshot_date,
        config_version=config_version,
    )
    if snapshot is None:
        raise HTTPException(status_code=404, detail="Technical snapshot not found")
    return TechnicalSnapshotRead.model_validate(snapshot)


@router.get(
    "/{ticker}/snapshots",
    response_model=TechnicalSnapshotHistoryRead,
)
async def read_snapshot_history(
    ticker: TickerPath,
    session: SessionDep,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
) -> TechnicalSnapshotHistoryRead:
    _validate_date_range(from_date, to_date)
    snapshots = await get_snapshot_history(
        session,
        ticker,
        start_date=from_date,
        end_date=to_date,
        limit=limit,
    )
    return TechnicalSnapshotHistoryRead(
        ticker=ticker.strip().upper(),
        from_date=from_date,
        to_date=to_date,
        count=len(snapshots),
        snapshots=snapshots,
    )


@router.get("/{ticker}/prices", response_model=StockPriceHistoryRead)
async def read_price_history(
    ticker: TickerPath,
    session: SessionDep,
    from_date: date | None = Query(default=None, alias="from"),
    to_date: date | None = Query(default=None, alias="to"),
    limit: int = Query(default=100, ge=1, le=500),
) -> StockPriceHistoryRead:
    _validate_date_range(from_date, to_date)
    prices = await get_stock_price_history(
        session,
        ticker,
        start_date=from_date,
        end_date=to_date,
        limit=limit,
    )
    return StockPriceHistoryRead(
        ticker=ticker.strip().upper(),
        from_date=from_date,
        to_date=to_date,
        count=len(prices),
        prices=prices,
    )
