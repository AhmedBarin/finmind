"""Market-data quality diagnostics and overall data-quality status."""

from dataclasses import dataclass
from enum import Enum
from typing import Sequence

import pandas as pd

from app.market_data.config import (
    EGX_HOLIDAYS,
    EGX_TRADING_WEEKDAYS,
    MAX_ABS_PRICE_CHANGE,
    MINIMUM_HISTORY_SESSIONS,
    PERCENTILE_HISTORY_SESSIONS,
    ZERO_VOLUME_LOOKBACK_SESSIONS,
)


class DataQualityStatus(str, Enum):
    VALID = "valid"
    STALE = "stale"
    INSUFFICIENT_HISTORY = "insufficient_history"
    FLAGGED = "flagged"


@dataclass(frozen=True)
class PriceJump:
    """A raw-close return exceeding the configured absolute threshold."""

    date: pd.Timestamp
    return_fraction: float


@dataclass(frozen=True)
class DataQualityDiagnostics:
    """Checks for one ticker; flags preserve details behind the overall status."""

    session_count: int
    status: DataQualityStatus | None
    flags: tuple[str, ...]
    insufficient_history: bool
    percentile_history_ready: bool
    duplicate_dates: tuple[pd.Timestamp, ...]
    out_of_order: bool
    missing_sessions: tuple[pd.Timestamp, ...]
    zero_volume_dates: tuple[pd.Timestamp, ...]
    volume_reliable: bool
    stale: bool | None
    missing_price_dates: tuple[pd.Timestamp, ...]
    unexplained_price_jumps: tuple[PriceJump, ...]


def inspect_price_history(
    prices: pd.DataFrame,
    *,
    as_of_date: object | None = None,
    expected_trading_sessions: Sequence[object] | None = None,
    max_abs_price_change: float = MAX_ABS_PRICE_CHANGE,
    minimum_history: int = MINIMUM_HISTORY_SESSIONS,
    percentile_history: int = PERCENTILE_HISTORY_SESSIONS,
    zero_volume_lookback: int = ZERO_VOLUME_LOOKBACK_SESSIONS,
) -> DataQualityDiagnostics:
    """Inspect one ticker's OHLCV frame without sorting, repairing, or mutating.

    Dates come from a Date column or index. The default provisional EGX calendar
    uses Sunday–Thursday and the configured holiday list. A supplied expected
    session list overrides it. Stale means more than one expected trading
    session has elapsed since the latest price, so an as-of date is required to
    assign an overall status. A price jump is a raw Close return above the
    configured threshold; a recorded dividend or split suppresses that flag.

    Fewer than 200 sessions is insufficient_history. From 200 through 251
    sessions remains valid if other checks pass, with limited_percentile_history
    recorded as a non-blocking flag. Zero volume only makes the Volume family
    unreliable; it does not by itself make the whole ticker flagged.
    """
    _validate_settings(minimum_history, percentile_history, zero_volume_lookback)
    if max_abs_price_change <= 0:
        raise ValueError("max_abs_price_change must be positive")
    as_of = _normalize_date(as_of_date) if as_of_date is not None else None

    required = {"Open", "High", "Low", "Close", "Adj Close", "Volume"}
    missing_columns = required - set(prices.columns)
    if missing_columns:
        raise ValueError(f"price history is missing columns: {sorted(missing_columns)}")

    date_values = prices["Date"] if "Date" in prices.columns else prices.index
    dates = pd.DatetimeIndex(pd.to_datetime(date_values, errors="raise")).normalize()
    if dates.isna().any():
        raise ValueError("price history contains missing dates")

    duplicate_dates = tuple(sorted(set(dates[dates.duplicated(keep=False)])))
    out_of_order = not dates.is_monotonic_increasing
    order = dates.argsort(kind="stable")
    sorted_dates = dates.take(order)
    sorted_prices = prices.iloc[order].copy()
    session_count = int(sorted_dates.nunique())

    if expected_trading_sessions is None:
        expected = _calendar_sessions(
            sorted_dates.min() if len(sorted_dates) else None,
            sorted_dates.max() if len(sorted_dates) else None,
        )
    else:
        expected = pd.DatetimeIndex(
            pd.to_datetime(list(expected_trading_sessions), errors="raise")
        ).normalize().unique().sort_values()
    if len(sorted_dates):
        within_history = expected[
            (expected >= sorted_dates.min()) & (expected <= sorted_dates.max())
        ]
        missing_sessions = tuple(within_history.difference(sorted_dates.unique()))
    else:
        missing_sessions = tuple(expected)

    required_price_columns = ["Open", "High", "Low", "Close", "Adj Close"]
    missing_price_mask = sorted_prices.loc[:, required_price_columns].isna().any(axis=1)
    missing_price_dates = tuple(sorted(set(sorted_dates[missing_price_mask.to_numpy()])))

    volume = pd.to_numeric(sorted_prices["Volume"], errors="raise")
    recent = volume.tail(zero_volume_lookback)
    zero_volume_dates = (
        tuple(sorted(set(sorted_dates[-len(recent):][recent.eq(0).to_numpy()])))
        if len(recent)
        else ()
    )
    volume_reliable = not zero_volume_dates

    close = pd.to_numeric(sorted_prices["Close"], errors="raise").astype("float64")
    returns = close.pct_change(fill_method=None)
    action_recorded = pd.Series(False, index=sorted_prices.index)
    for action_column in ("Dividends", "Stock Splits"):
        if action_column in sorted_prices.columns:
            actions = pd.to_numeric(sorted_prices[action_column], errors="raise")
            action_recorded |= actions.fillna(0).ne(0)
    jump_mask = returns.abs().gt(max_abs_price_change) & ~action_recorded
    jumps = tuple(
        PriceJump(date=pd.Timestamp(day), return_fraction=float(change))
        for day, change in zip(
            sorted_dates[jump_mask.to_numpy()], returns[jump_mask].to_numpy()
        )
    )

    stale = None
    if as_of is not None:
        if len(sorted_dates) == 0:
            stale = True
        else:
            latest = sorted_dates.max()
            if as_of < latest:
                raise ValueError("as_of_date cannot be earlier than the latest price date")
            sessions_after_latest = _calendar_sessions(latest + pd.Timedelta(days=1), as_of)
            stale = len(sessions_after_latest) > 1

    insufficient_history = session_count < minimum_history
    percentile_history_ready = session_count >= percentile_history
    flags: list[str] = []
    if minimum_history <= session_count < percentile_history:
        flags.append("limited_percentile_history")
    if missing_price_dates:
        flags.append("missing_price_data")
    if duplicate_dates:
        flags.append("duplicate_dates")
    if out_of_order:
        flags.append("out_of_order_dates")
    if missing_sessions:
        flags.append("missing_sessions")
    if jumps:
        flags.append("unexplained_price_jump")
    if zero_volume_dates:
        flags.append("zero_volume_sessions")
    if stale:
        flags.append("stale")

    blocking_flags = {
        "missing_price_data",
        "duplicate_dates",
        "out_of_order_dates",
        "missing_sessions",
        "unexplained_price_jump",
    }
    if insufficient_history:
        status = DataQualityStatus.INSUFFICIENT_HISTORY
    elif stale:
        status = DataQualityStatus.STALE
    elif blocking_flags.intersection(flags):
        status = DataQualityStatus.FLAGGED
    else:
        status = DataQualityStatus.VALID

    return DataQualityDiagnostics(
        session_count=session_count,
        status=status if as_of is not None else None,
        flags=tuple(flags),
        insufficient_history=insufficient_history,
        percentile_history_ready=percentile_history_ready,
        duplicate_dates=duplicate_dates,
        out_of_order=out_of_order,
        missing_sessions=missing_sessions,
        zero_volume_dates=zero_volume_dates,
        volume_reliable=volume_reliable,
        stale=stale,
        missing_price_dates=missing_price_dates,
        unexplained_price_jumps=jumps,
    )


def _validate_settings(
    minimum_history: int, percentile_history: int, zero_volume_lookback: int
) -> None:
    values = {
        "minimum_history": minimum_history,
        "percentile_history": percentile_history,
        "zero_volume_lookback": zero_volume_lookback,
    }
    if any(
        isinstance(value, bool) or not isinstance(value, int) or value < 1
        for value in values.values()
    ):
        raise ValueError("history and lookback settings must be positive integers")
    if percentile_history < minimum_history:
        raise ValueError("percentile_history cannot be less than minimum_history")


def _normalize_date(value: object) -> pd.Timestamp:
    normalized = pd.Timestamp(pd.to_datetime(value, errors="raise")).normalize()
    if pd.isna(normalized):
        raise ValueError("as_of_date cannot be missing")
    return normalized


def _calendar_sessions(
    start: pd.Timestamp | None, end: pd.Timestamp | None
) -> pd.DatetimeIndex:
    if start is None or end is None or end < start:
        return pd.DatetimeIndex([])
    dates = pd.date_range(start.normalize(), end.normalize(), freq="D")
    holidays = {pd.Timestamp(day) for day in EGX_HOLIDAYS}
    return pd.DatetimeIndex(
        day for day in dates
        if day.weekday() in EGX_TRADING_WEEKDAYS and day not in holidays
    )
