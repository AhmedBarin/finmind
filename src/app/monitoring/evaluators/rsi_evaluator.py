"""RSI threshold evaluator."""

from __future__ import annotations

from datetime import UTC, datetime

from app.monitoring.schemas.market_data import (
    EvaluationResult,
    MarketDataPoint,
    TechnicalSignals,
)
from app.monitoring.schemas.rules import Direction, RSIThresholdParams


def evaluate_rsi_threshold(
    params: RSIThresholdParams,
    market_data: MarketDataPoint,
    signals: TechnicalSignals,
) -> EvaluationResult:
    """Evaluate whether RSI is above/below the given threshold."""
    try:
        if signals.rsi is None:
            return EvaluationResult(
                triggered=False,
                reason="RSI value is not available",
                error=True,
                error_message="signals.rsi is None",
                evidence={
                    "ticker": signals.ticker,
                    "date": str(signals.date),
                    "evaluated_at": datetime.now(tz=UTC).isoformat(),
                },
            )

        triggered = (
            signals.rsi > params.threshold
            if params.direction == Direction.above
            else signals.rsi < params.threshold
        )

        direction_label = "above" if params.direction == Direction.above else "below"
        reason = (
            f"RSI {signals.rsi:.2f} is {direction_label} threshold {params.threshold}"
            if triggered
            else f"RSI {signals.rsi:.2f} has not crossed {direction_label} threshold {params.threshold}"
        )

        return EvaluationResult(
            triggered=triggered,
            reason=reason,
            current_value=signals.rsi,
            threshold_value=params.threshold,
            evidence={
                "rsi": signals.rsi,
                "threshold": params.threshold,
                "direction": params.direction.value,
                "ticker": signals.ticker,
                "date": str(signals.date),
                "evaluated_at": datetime.now(tz=UTC).isoformat(),
            },
        )
    except Exception as exc:  # noqa: BLE001
        return EvaluationResult(
            triggered=False,
            reason="RSI evaluation failed",
            error=True,
            error_message=str(exc),
            evidence={
                "ticker": signals.ticker,
                "date": str(signals.date),
                "evaluated_at": datetime.now(tz=UTC).isoformat(),
            },
        )
