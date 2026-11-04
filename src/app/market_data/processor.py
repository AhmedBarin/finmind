"""Pure OHLCV normalization for adjusted-price indicator inputs."""

import pandas as pd


RAW_PRICE_COLUMNS = ("Open", "High", "Low", "Close", "Adj Close")
REQUIRED_COLUMNS = (*RAW_PRICE_COLUMNS, "Volume")
ADJUSTED_COLUMNS = ("adj_open", "adj_high", "adj_low", "adj_close")


def normalize_ohlcv(raw: pd.DataFrame) -> pd.DataFrame:
    """Add adjusted OHLC columns while preserving every original raw column.

    ``factor = Adj Close / Close``. Adjusted Open/High/Low are raw values
    multiplied by the factor; adjusted Close is Yahoo's Adj Close. Missing or
    zero raw Close values produce a missing factor and adjusted OHLC values;
    this function does not drop or repair rows. A later quality check should
    decide whether such rows can be used.
    """
    missing = [column for column in REQUIRED_COLUMNS if column not in raw.columns]
    if missing:
        raise ValueError(f"OHLCV input is missing required columns: {missing}")

    result = raw.copy(deep=True)
    numeric = {
        column: pd.to_numeric(raw[column], errors="raise").astype("float64")
        for column in REQUIRED_COLUMNS
    }
    raw_close = numeric["Close"]
    adj_close = numeric["Adj Close"]
    factor = adj_close.div(raw_close.where(raw_close.ne(0)))
    result["adjustment_factor"] = factor
    result["adj_open"] = numeric["Open"] * factor
    result["adj_high"] = numeric["High"] * factor
    result["adj_low"] = numeric["Low"] * factor
    result["adj_close"] = adj_close
    return result


def prepare_indicator_inputs(processed: pd.DataFrame) -> pd.DataFrame:
    """Return adjusted OHLC, raw close for liquidity, and volume only.

    Dividend/split action columns remain in ``processed`` for raw storage or
    audit, but are intentionally omitted from this indicator-input view.
    """
    required = (*ADJUSTED_COLUMNS, "Close", "Volume")
    missing = [column for column in required if column not in processed.columns]
    if missing:
        raise ValueError(f"Processed market data is missing columns: {missing}")
    return processed.loc[:, [
        "adj_open", "adj_high", "adj_low", "adj_close", "Close", "Volume"
    ]].rename(
        columns={
            "adj_open": "open",
            "adj_high": "high",
            "adj_low": "low",
            "adj_close": "close",
            "Close": "raw_close",
            "Volume": "volume",
        }
    ).copy()

