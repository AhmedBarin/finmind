"""Cross-sectional EGX30 liquidity percentile calculation and persistence."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date
import hashlib
import json
import math

from sqlalchemy.ext.asyncio import AsyncSession

from app.technical_analysis.config import (
    EGX30_TICKERS,
    EGX30_UNIVERSE_VERSION,
    LIQUIDITY_RANK_LOOKBACK_SESSIONS,
)
from app.technical_analysis.models import TechnicalSnapshot
from app.technical_analysis.repository import (
    get_snapshot_by_date,
    save_technical_snapshot,
)


@dataclass(frozen=True)
class LiquidityRankReport:
    as_of_date: date
    universe: tuple[str, ...]
    ranked_tickers: tuple[str, ...]
    unavailable_tickers: tuple[str, ...]
    snapshot_ids: tuple[str, ...]


def rank_liquidity_values(
    traded_values: Mapping[str, object],
    *,
    universe_tickers: Sequence[str] = EGX30_TICKERS,
) -> dict[str, float]:
    """Return ascending average-rank percentiles, where 100 is most liquid.

    Values should be each ticker's 20-session average raw Close * Volume.
    Missing, non-finite, or negative values are excluded from the denominator.
    Equal values receive the average rank of their tied positions.
    """
    universe = _normalize_universe(universe_tickers)
    normalized_values: dict[str, float] = {}
    for ticker, raw_value in traded_values.items():
        normalized_ticker = _normalize_ticker(ticker)
        if normalized_ticker not in universe:
            continue
        value = _finite_value(raw_value)
        if value is not None and value >= 0:
            normalized_values[normalized_ticker] = value

    ordered = sorted(normalized_values.items(), key=lambda item: (item[1], item[0]))
    count = len(ordered)
    if not count:
        return {}

    result: dict[str, float] = {}
    start = 0
    while start < count:
        end = start + 1
        while end < count and ordered[end][1] == ordered[start][1]:
            end += 1
        # Ranks are one-based, and tied entries receive their average rank.
        average_rank = ((start + 1) + end) / 2
        percentile = average_rank / count * 100.0
        for ticker, _ in ordered[start:end]:
            result[ticker] = percentile
        start = end
    return result


async def rank_egx30_snapshots(
    session: AsyncSession,
    as_of_date: date,
    *,
    universe_tickers: Sequence[str] = EGX30_TICKERS,
    universe_version: str = EGX30_UNIVERSE_VERSION,
) -> LiquidityRankReport:
    """Persist ranked snapshot variants for available valid EGX30 snapshots.

    This does not mutate existing snapshots. It saves a new immutable snapshot
    whose input data and hash include the cross-sectional ranking inputs.
    """
    universe = _normalize_universe(universe_tickers)
    if not universe_version.strip():
        raise ValueError("universe_version must not be empty")

    snapshots: dict[str, TechnicalSnapshot] = {}
    values: dict[str, float] = {}
    for ticker in universe:
        snapshot = await get_snapshot_by_date(session, ticker, as_of_date)
        if snapshot is None or snapshot.data_quality_status != "valid":
            continue
        traded_value = _finite_value(
            snapshot.indicators.get("avg_traded_value_20d")
        )
        if traded_value is None or traded_value < 0:
            continue
        snapshots[ticker] = snapshot
        values[ticker] = traded_value

    ranks = rank_liquidity_values(values, universe_tickers=universe)
    ranked_tickers = tuple(sorted(ranks))
    unavailable = tuple(sorted(set(universe) - set(ranked_tickers)))
    ranked_value_payload = {
        ticker: values[ticker] for ticker in sorted(values)
    }
    source_input_hashes: dict[str, str] = {}
    for ticker, snapshot in snapshots.items():
        source_hash = (snapshot.input_data or {}).get("source_snapshot_input_hash")
        if source_hash is None:
            previous_rank_data = (snapshot.input_data or {}).get("liquidity_rank", {})
            previous_hashes = previous_rank_data.get(
                "ranked_snapshot_input_hashes", {}
            )
            source_hash = previous_hashes.get(ticker, snapshot.input_hash)
        source_input_hashes[ticker] = str(source_hash)
    rank_metadata = {
        "universe": "EGX30",
        "universe_version": universe_version,
        "as_of_date": as_of_date.isoformat(),
        "lookback_sessions": LIQUIDITY_RANK_LOOKBACK_SESSIONS,
        "method": "ascending_average_rank_percentile",
        "percentile_scale": "0_to_100_higher_is_more_liquid",
        "ranked_traded_values": ranked_value_payload,
        "ranked_snapshot_input_hashes": {
            ticker: source_input_hashes[ticker] for ticker in sorted(source_input_hashes)
        },
        "unavailable_tickers": list(unavailable),
    }

    saved_ids: list[str] = []
    for ticker in ranked_tickers:
        snapshot = snapshots[ticker]
        input_data = dict(snapshot.input_data or {})
        input_data["source_snapshot_input_hash"] = source_input_hashes[ticker]
        input_data["liquidity_rank"] = rank_metadata
        input_hash = hashlib.sha256(
            json.dumps(
                input_data,
                sort_keys=True,
                separators=(",", ":"),
                ensure_ascii=False,
                allow_nan=False,
            ).encode("utf-8")
        ).hexdigest()
        indicators = dict(snapshot.indicators or {})
        indicators["liquidity_rank_pct"] = ranks[ticker]
        indicators["liquidity_rank_universe_count"] = len(ranks)
        indicators["liquidity_rank_universe_expected"] = len(universe)

        saved = await save_technical_snapshot(
            session,
            {
                "ticker": snapshot.ticker,
                "date": snapshot.date,
                "config_version": snapshot.config_version,
                "input_hash": input_hash,
                "data_quality_status": snapshot.data_quality_status,
                "rsi": snapshot.rsi,
                "sma_20": snapshot.sma_20,
                "sma_50": snapshot.sma_50,
                "atr": snapshot.atr,
                "setup_score": snapshot.setup_score,
                "regime": snapshot.regime,
                "risk_label": snapshot.risk_label,
                "input_data": input_data,
                "indicators": indicators,
                "scores": dict(snapshot.scores or {}),
                "quality_flags": list(snapshot.quality_flags or []),
            },
        )
        saved_ids.append(str(saved.id))

    return LiquidityRankReport(
        as_of_date=as_of_date,
        universe=universe,
        ranked_tickers=ranked_tickers,
        unavailable_tickers=unavailable,
        snapshot_ids=tuple(saved_ids),
    )


def _normalize_universe(tickers: Sequence[str]) -> tuple[str, ...]:
    normalized = tuple(_normalize_ticker(ticker) for ticker in tickers)
    if not normalized:
        raise ValueError("universe_tickers must not be empty")
    if len(set(normalized)) != len(normalized):
        raise ValueError("universe_tickers must not contain duplicates")
    return normalized


def _normalize_ticker(ticker: str) -> str:
    normalized = ticker.strip().upper()
    if not normalized:
        raise ValueError("ticker must not be empty")
    return normalized


def _finite_value(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None
