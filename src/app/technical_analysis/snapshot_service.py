"""Build and persist deterministic per-ticker technical snapshots."""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date, datetime, timedelta
from decimal import Decimal
import hashlib
import json
import math
from typing import Any

import numpy as np
import pandas as pd
from sqlalchemy.ext.asyncio import AsyncSession

from app.market_data.processor import normalize_ohlcv, prepare_indicator_inputs
from app.market_data.quality import DataQualityDiagnostics, inspect_price_history
from app.market_data.repository import get_stock_price_history
from app.technical_analysis.config import (
    CONFIG_VERSION,
    SNAPSHOT_INPUT_HISTORY_SESSIONS,
)
from app.technical_analysis.indicators.liquidity import average_traded_value
from app.technical_analysis.indicators.momentum import macd, rsi
from app.technical_analysis.indicators.moving_average import sma
from app.technical_analysis.indicators.statistics import rolling_percentile_rank
from app.technical_analysis.indicators.support_resistance import support_resistance
from app.technical_analysis.indicators.trend import adx
from app.technical_analysis.indicators.volatility import atr, atr_percent, bollinger_bands
from app.technical_analysis.indicators.volume import daily_return, obv, volume_ratio, volume_sma
from app.technical_analysis.models import TechnicalSnapshot
from app.technical_analysis.regime import Regime, classify_regime
from app.technical_analysis.repository import (
    get_snapshot_history,
    save_technical_snapshot,
)
from app.technical_analysis.risk import classify_risk
from app.technical_analysis.scoring.momentum import momentum_family_score
from app.technical_analysis.scoring.normalization import score_state
from app.technical_analysis.scoring.setup_score import calculate_setup_score
from app.technical_analysis.scoring.support_resistance import (
    support_resistance_score,
)
from app.technical_analysis.scoring.trend import trend_family_score
from app.technical_analysis.scoring.types import FamilyScore
from app.technical_analysis.scoring.volume import (
    volume_family_score,
    volume_is_reliable,
)


_RAW_COLUMNS = [
    "Date",
    "Open",
    "High",
    "Low",
    "Close",
    "Adj Close",
    "Volume",
    "Dividends",
    "Stock Splits",
]


async def calculate_and_persist_snapshot(
    session: AsyncSession,
    ticker: str,
    as_of_date: date,
    *,
    config_version: str = CONFIG_VERSION,
    expected_trading_sessions: Sequence[object] | None = None,
) -> TechnicalSnapshot:
    """Run quality checks first, calculate the available outputs, and persist.

    The supplied date is the calendar date used to judge staleness. The saved
    snapshot date is the latest actual price date (or ``as_of_date`` if no
    price exists). Database transactions are managed by the caller.
    """
    if not ticker.strip():
        raise ValueError("ticker must not be empty")
    if not config_version.strip():
        raise ValueError("config_version must not be empty")

    rows = await get_stock_price_history(
        session, ticker, end_date=as_of_date
    )
    all_prices = _prices_frame(rows)
    diagnostics = inspect_price_history(
        all_prices,
        as_of_date=as_of_date,
        expected_trading_sessions=expected_trading_sessions,
    )
    snapshot_date = rows[-1].date if rows else as_of_date

    if rows:
        window_frame = all_prices.tail(SNAPSHOT_INPUT_HISTORY_SESSIONS).reset_index(
            drop=True
        )
        processed = normalize_ohlcv(window_frame)
        inputs = prepare_indicator_inputs(processed)
        indicators, families, regime, risk_label, setup = _calculate_outputs(
            inputs,
            diagnostics,
            previous_regime=await _previous_regime(
                session, ticker, snapshot_date
            ),
        )
        input_data = {
            "as_of_date": as_of_date,
            "history_session_count": diagnostics.session_count,
            "calculation_window_sessions": len(window_frame),
            "source_window": window_frame.to_dict(orient="records"),
            "data_quality": _quality_payload(diagnostics),
        }
        scores = _scores_payload(families, regime, setup, risk_label)
    else:
        indicators = {}
        families = _unavailable_families("No price history is available.")
        regime = None
        risk_label = None
        setup = None
        input_data = {
            "as_of_date": as_of_date,
            "history_session_count": 0,
            "calculation_window_sessions": 0,
            "source_window": [],
            "data_quality": _quality_payload(diagnostics),
        }
        scores = _scores_payload(families, regime, setup, risk_label)

    status = diagnostics.status.value if diagnostics.status is not None else "flagged"
    safe_input_data = _json_safe(input_data)
    input_hash = hashlib.sha256(
        json.dumps(
            safe_input_data,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
        ).encode("utf-8")
    ).hexdigest()
    snapshot_values = {
        "ticker": ticker.strip().upper(),
        "date": snapshot_date,
        "config_version": config_version,
        "input_hash": input_hash,
        "data_quality_status": status,
        "rsi": indicators.get("rsi14"),
        "sma_20": indicators.get("sma20"),
        "sma_50": indicators.get("sma50"),
        "atr": indicators.get("atr14"),
        "setup_score": setup.score if setup is not None else None,
        "regime": regime.value if regime is not None else None,
        "risk_label": risk_label.value if risk_label is not None else None,
        "input_data": safe_input_data,
        "indicators": _json_safe(indicators),
        "scores": _json_safe(scores),
        "quality_flags": list(diagnostics.flags),
    }
    return await save_technical_snapshot(session, snapshot_values)


async def _previous_regime(
    session: AsyncSession,
    ticker: str,
    snapshot_date: date,
) -> Regime | None:
    previous = await get_snapshot_history(
        session,
        ticker,
        end_date=snapshot_date - timedelta(days=1),
        limit=1,
    )
    if not previous or previous[0].regime is None:
        return None
    return Regime(previous[0].regime)


def _calculate_outputs(
    inputs: pd.DataFrame,
    diagnostics: DataQualityDiagnostics,
    *,
    previous_regime: Regime | None,
) -> tuple[dict[str, Any], dict[str, FamilyScore], Regime | None, Any, Any]:
    close = inputs["close"].astype("float64")
    high = inputs["high"].astype("float64")
    low = inputs["low"].astype("float64")
    raw_close = inputs["raw_close"].astype("float64")
    volume = inputs["volume"].astype("float64")

    sma20 = sma(close, 20)
    sma50 = sma(close, 50)
    sma200 = sma(close, 200)
    rsi14 = rsi(close, 14)
    macd_values = macd(close)
    atr14 = atr(high, low, close, 14)
    atr_pct = atr_percent(atr14, close)
    atr_pct_percentile = rolling_percentile_rank(atr_pct, 252)
    bands = bollinger_bands(close, 20, 2.0)
    bb_width_percentile = rolling_percentile_rank(bands["bb_width"], 252)
    volume_sma20 = volume_sma(volume, 20, exclude_today=True)
    volume_ratio_values = volume_ratio(volume, volume_sma20)
    daily_return_pct = daily_return(close, percent=True)
    obv_values = obv(close, volume)
    traded_value20 = average_traded_value(raw_close, volume, 20)
    adx_values = adx(high, low, close, 14)

    current = {
        "close": _last(close),
        "sma20": _last(sma20),
        "sma50": _last(sma50),
        "sma200": _last(sma200),
        "rsi14": _last(rsi14),
        "macd": _last(macd_values["macd"]),
        "macd_signal": _last(macd_values["macd_signal"]),
        "macd_hist": _last(macd_values["macd_hist"]),
        "macd_hist_prev": _last(macd_values["macd_hist_prev"]),
        "atr14": _last(atr14),
        "atr_pct": _last(atr_pct),
        "atr_pct_percentile_1y": _last(atr_pct_percentile),
        "bb_middle": _last(bands["bb_middle"]),
        "bb_upper": _last(bands["bb_upper"]),
        "bb_lower": _last(bands["bb_lower"]),
        "bb_width": _last(bands["bb_width"]),
        "bb_width_percentile_1y": _last(bb_width_percentile),
        "volume_sma20": _last(volume_sma20),
        "volume_ratio": _last(volume_ratio_values),
        "obv": _last(obv_values),
        "daily_return": _last(daily_return(close)),
        "daily_return_pct": _last(daily_return_pct),
        "avg_traded_value_20d": _last(traded_value20),
        # Universe rank requires a separate cross-ticker pass and confirmed universe.
        "liquidity_rank_pct": None,
        "adx14": _last(adx_values["adx"]),
        "plus_di": _last(adx_values["plus_di"]),
        "minus_di": _last(adx_values["minus_di"]),
        "dx": _last(adx_values["dx"]),
    }

    regime = (
        classify_regime(current["adx14"], previous_regime)
        if current["adx14"] is not None
        else None
    )
    risk_label = classify_risk(current["atr_pct_percentile_1y"])
    recent_volume = volume.tail(20)
    try:
        volume_reliable = diagnostics.volume_reliable and volume_is_reliable(
            recent_volume
        )
    except ValueError:
        volume_reliable = False

    families = _unavailable_families("Required indicator inputs are unavailable.")
    if regime is not None:
        try:
            if all(
                current[key] is not None
                for key in ("close", "sma20", "sma50", "sma200", "atr14")
            ) and current["atr14"] > 0:
                families["trend"] = trend_family_score(
                    current["close"],
                    current["sma20"],
                    current["sma50"],
                    current["sma200"],
                    current["atr14"],
                )
        except ValueError:
            pass
        try:
            if all(
                current[key] is not None
                for key in ("rsi14", "macd_hist", "macd_hist_prev")
            ):
                families["momentum"] = momentum_family_score(
                    current["rsi14"],
                    current["macd_hist"],
                    current["macd_hist_prev"],
                    regime,
                )
        except ValueError:
            pass

    try:
        if volume_reliable and all(
            current[key] is not None
            for key in ("volume_ratio", "daily_return_pct", "atr_pct")
        ):
            families["volume"] = volume_family_score(
                current["volume_ratio"],
                current["daily_return_pct"],
                current["atr_pct"],
                volume_reliable=True,
            )
        else:
            families["volume"] = volume_family_score(
                0.0, 0.0, 1.0, volume_reliable=False
            )
    except ValueError:
        pass

    sr: dict[str, Any] = {}
    latest_atr = current["atr14"]
    if latest_atr is not None and latest_atr > 0 and current["close"] is not None:
        latest_volume_ratio = current["volume_ratio"]
        if latest_volume_ratio is None or not math.isfinite(latest_volume_ratio):
            latest_volume_ratio = 0.0
        try:
            levels = support_resistance(
                high,
                low,
                close,
                latest_atr,
                latest_volume_ratio,
            )
            sr = {
                "support": levels.support,
                "resistance": levels.resistance,
                "support_touches": levels.support_touches,
                "resistance_touches": levels.resistance_touches,
                "breakout": levels.breakout,
                "breakdown": levels.breakdown,
            }
            current.update(sr)
            families["support_resistance"] = support_resistance_score(
                current["close"],
                levels.support,
                levels.resistance,
                latest_atr,
                breakout=levels.breakout,
                breakdown=levels.breakdown,
            )
        except ValueError:
            pass

    setup = calculate_setup_score(families, regime) if regime is not None else None
    current["volume_reliable"] = volume_reliable
    return current, families, regime, risk_label, setup


def _unavailable_families(reason: str) -> dict[str, FamilyScore]:
    return {
        name: FamilyScore(score=None, reliable=False, reasons={name: reason})
        for name in ("trend", "momentum", "volume", "support_resistance")
    }


def _last(values: pd.Series) -> float | None:
    if values.empty or pd.isna(values.iloc[-1]):
        return None
    value = float(values.iloc[-1])
    return value if math.isfinite(value) else None


def _prices_frame(rows: list[Any]) -> pd.DataFrame:
    records = [
        {
            "Date": row.date,
            "Open": _float_or_none(row.raw_open),
            "High": _float_or_none(row.raw_high),
            "Low": _float_or_none(row.raw_low),
            "Close": _float_or_none(row.raw_close),
            "Adj Close": _float_or_none(row.adj_close),
            "Volume": row.volume,
            "Dividends": _float_or_none(row.dividends),
            "Stock Splits": _float_or_none(row.stock_splits),
        }
        for row in rows
    ]
    return pd.DataFrame.from_records(records, columns=_RAW_COLUMNS)


def _float_or_none(value: Decimal | float | int | None) -> float | None:
    return float(value) if value is not None else None


def _quality_payload(diagnostics: DataQualityDiagnostics) -> dict[str, Any]:
    return {
        "status": diagnostics.status.value if diagnostics.status else None,
        "session_count": diagnostics.session_count,
        "flags": list(diagnostics.flags),
        "volume_reliable": diagnostics.volume_reliable,
        "percentile_history_ready": diagnostics.percentile_history_ready,
        "duplicate_dates": diagnostics.duplicate_dates,
        "out_of_order": diagnostics.out_of_order,
        "missing_sessions": diagnostics.missing_sessions,
        "missing_price_dates": diagnostics.missing_price_dates,
        "zero_volume_dates": diagnostics.zero_volume_dates,
        "unexplained_price_jumps": [
            {"date": jump.date, "return_fraction": jump.return_fraction}
            for jump in diagnostics.unexplained_price_jumps
        ],
    }


def _scores_payload(
    families: dict[str, FamilyScore],
    regime: Regime | None,
    setup: Any,
    risk_label: Any,
) -> dict[str, Any]:
    family_payload: dict[str, Any] = {}
    for name, family in families.items():
        state = score_state(family.score).value if family.score is not None else None
        family_payload[name] = {
            "score": family.score,
            "state": state,
            "reliable": family.reliable,
            "indicator_scores": family.indicator_scores,
            "reasons": family.reasons,
        }
    return {
        "regime": regime.value if regime is not None else None,
        "risk_label": risk_label.value if risk_label is not None else None,
        "family_scores": family_payload,
        "setup_score": (
            {
                "score": setup.score,
                "applied_weights": setup.applied_weights,
                "unreliable_families": setup.unreliable_families,
                "reason": setup.reason,
            }
            if setup is not None
            else None
        ),
    }


def _json_safe(value: Any) -> Any:
    if value is None or value is pd.NA or value is pd.NaT:
        return None
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, (pd.Timestamp, datetime, date)):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, np.generic):
        return _json_safe(value.item())
    if isinstance(value, float):
        return value if math.isfinite(value) else None
    if pd.isna(value):
        return None
    return value
