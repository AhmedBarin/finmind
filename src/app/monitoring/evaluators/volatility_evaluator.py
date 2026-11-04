"""Volatility (ATR %) threshold evaluator."""

from __future__ import annotations

from datetime import UTC, datetime

from app.monitoring.schemas.market_data import (
    EvaluationResult,
    MarketDataPoint,
    TechnicalSignals,
)
from app.monitoring.schemas.rules import VolatilityThresholdParams


def evaluate_volatility(
    params: VolatilityThresholdParams,
    market_data: MarketDataPoint,
    signals: TechnicalSignals,
) -> EvaluationResult:
    """Trigger when ATR as a percentage of close exceeds the threshold."""
    try:
        if signals.atr is None:
            return EvaluationResult(
                triggered=False,
                reason="ATR value is not available",
                error=True,
                error_message="signals.atr is None",
                evidence={
                    "ticker": signals.ticker,
                    "date": str(signals.date),
                    "evaluated_at": datetime.now(tz=UTC).isoformat(),
                },
            )

        if market_data.close == 0:
            return EvaluationResult(
                triggered=False,
                reason="Close price is zero, cannot compute ATR %",
                error=True,
                error_message="market_data.close is 0",
                evidence={
                    "ticker": signals.ticker,
                    "date": str(signals.date),
                    "evaluated_at": datetime.now(tz=UTC).isoformat(),
                },
            )

        atr_pct = (signals.atr / market_data.close) * 100
        triggered = atr_pct > params.atr_pct_threshold

        reason = (
            f"ATR% {atr_pct:.2f}% exceeds threshold {params.atr_pct_threshold}%"
            if triggered
            else f"ATR% {atr_pct:.2f}% is within threshold {params.atr_pct_threshold}%"
        )

        return EvaluationResult(
            triggered=triggered,
            reason=reason,
            current_value=atr_pct,
            threshold_value=params.atr_pct_threshold,
            evidence={
                "atr": signals.atr,
                "close": market_data.close,
                "atr_pct": round(atr_pct, 4),
                "atr_pct_threshold": params.atr_pct_threshold,
                "ticker": signals.ticker,
                "date": str(signals.date),
                "evaluated_at": datetime.now(tz=UTC).isoformat(),
            },
        )
    except Exception as exc:  # noqa: BLE001
        return EvaluationResult(
            triggered=False,
            reason="Volatility evaluation failed",
            error=True,
            error_message=str(exc),
            evidence={
                "ticker": signals.ticker,
                "date": str(signals.date),
                "evaluated_at": datetime.now(tz=UTC).isoformat(),
            },
        )
