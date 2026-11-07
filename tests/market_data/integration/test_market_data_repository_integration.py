from datetime import date
from decimal import Decimal
from uuid import uuid4

import pytest
import pytest_asyncio

from app.db.session import SessionLocal, engine
from app.market_data.repository import (
    get_latest_stock_price,
    get_stock_price_by_date,
    get_stock_price_history,
    upsert_stock_price,
)


@pytest_asyncio.fixture
async def db_session():
    try:
        async with SessionLocal() as session:
            transaction = await session.begin()
            try:
                yield session
            finally:
                await transaction.rollback()
    finally:
        await engine.dispose()


@pytest.mark.asyncio
async def test_stock_price_upsert_and_reads(db_session) -> None:
    ticker = f"T{uuid4().hex[:10]}".upper()
    price_date = date(2025, 1, 2)
    first = await upsert_stock_price(
        db_session,
        {
            "ticker": ticker,
            "date": price_date,
            "source": "test",
            "raw_close": Decimal("10.000000"),
            "adj_close": Decimal("9.500000"),
            "volume": 1000,
        },
    )
    await db_session.flush()

    updated = await upsert_stock_price(
        db_session,
        {
            "ticker": ticker,
            "date": price_date,
            "source": "test",
            "raw_close": Decimal("11.000000"),
            "adj_close": Decimal("10.450000"),
            "volume": 1200,
        },
    )
    await db_session.flush()

    assert updated.id == first.id
    assert updated.raw_close == Decimal("11.000000")
    assert updated.volume == 1200
    assert (await get_stock_price_by_date(db_session, ticker, price_date)).id == first.id
    assert (await get_latest_stock_price(db_session, ticker)).id == first.id
    history = await get_stock_price_history(db_session, ticker)
    assert [row.date for row in history] == [price_date]


def test_stock_price_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValueError, match="unknown or managed"):
        from app.market_data.repository import _price_payload

        _price_payload(
            {
                "ticker": "ABC.CA",
                "date": date(2025, 1, 2),
                "source": "test",
                "unexpected": 1,
            }
        )
