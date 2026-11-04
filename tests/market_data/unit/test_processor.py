import pandas as pd
import pandas.testing as pdt
import pytest

from app.market_data.processor import normalize_ohlcv, prepare_indicator_inputs


def _raw_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "Open": [10.0, 20.0],
            "High": [12.0, 24.0],
            "Low": [9.0, 18.0],
            "Close": [10.0, 20.0],
            "Adj Close": [5.0, 10.0],
            "Volume": [100.0, 200.0],
            "Dividends": [0.0, 1.0],
            "Stock Splits": [0.0, 0.0],
        },
        index=pd.to_datetime(["2024-01-01", "2024-01-02"]),
    )


def test_normalize_ohlcv_adds_adjusted_prices_and_preserves_raw_data() -> None:
    raw = _raw_frame()
    original = raw.copy(deep=True)
    result = normalize_ohlcv(raw)

    assert result["adjustment_factor"].tolist() == [0.5, 0.5]
    assert result["adj_open"].tolist() == [5.0, 10.0]
    assert result["adj_high"].tolist() == [6.0, 12.0]
    assert result["adj_low"].tolist() == [4.5, 9.0]
    assert result["adj_close"].tolist() == [5.0, 10.0]
    pdt.assert_frame_equal(raw, original)
    pdt.assert_frame_equal(result.loc[:, original.columns], original)


def test_indicator_inputs_exclude_actions_and_preserve_raw_close_for_liquidity() -> None:
    processed = normalize_ohlcv(_raw_frame())
    inputs = prepare_indicator_inputs(processed)

    assert inputs.columns.tolist() == [
        "open", "high", "low", "close", "raw_close", "volume"
    ]
    assert inputs["close"].tolist() == [5.0, 10.0]
    assert inputs["raw_close"].tolist() == [10.0, 20.0]
    assert "Dividends" not in inputs and "Stock Splits" not in inputs


def test_missing_price_rows_are_preserved_and_adjusted_values_remain_missing() -> None:
    raw = _raw_frame()
    raw.loc[raw.index[0], "Close"] = float("nan")
    result = normalize_ohlcv(raw)

    assert len(result) == len(raw)
    assert pd.isna(result.loc[raw.index[0], "adjustment_factor"])
    assert pd.isna(result.loc[raw.index[0], "adj_open"])
    assert result.loc[raw.index[0], "adj_close"] == 5.0


def test_zero_close_does_not_create_infinite_adjustments() -> None:
    raw = _raw_frame()
    raw.loc[raw.index[0], "Close"] = 0.0
    result = normalize_ohlcv(raw)

    assert pd.isna(result.loc[raw.index[0], "adjustment_factor"])
    assert pd.isna(result.loc[raw.index[0], "adj_open"])
    assert result.loc[raw.index[0], "adj_close"] == 5.0


def test_missing_required_columns_are_reported() -> None:
    with pytest.raises(ValueError, match="required columns"):
        normalize_ohlcv(_raw_frame().drop(columns="Adj Close"))

