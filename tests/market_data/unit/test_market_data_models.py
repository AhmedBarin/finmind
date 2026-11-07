from app.market_data.models import StockPrice


def test_stock_price_keeps_raw_and_adjusted_ohlc() -> None:
    columns = StockPrice.__table__.columns

    assert {"raw_open", "raw_high", "raw_low", "raw_close"} <= set(columns.keys())
    assert {"adj_open", "adj_high", "adj_low", "adj_close"} <= set(columns.keys())
    assert "volume" in columns


def test_stock_price_is_unique_per_ticker_and_date() -> None:
    constraints = [
        constraint
        for constraint in StockPrice.__table__.constraints
        if constraint.name == "uq_stock_prices_ticker_date"
    ]

    assert len(constraints) == 1
    assert [column.name for column in constraints[0].columns] == ["ticker", "date"]
