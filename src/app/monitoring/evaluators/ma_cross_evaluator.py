"""Moving-average crossover evaluator (stateful)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.monitoring.schemas.market_data import (
    EvaluationResult,
    MarketDataPoint,
    TechnicalSignals,
)
from app.monitoring.schemas.rules import Direction, PriceMACrossParams

if TYPE_CHECKING:
    from app.monitoring.models.monitoring_rule_state import MonitoringRuleState


def evaluate_ma_cross(
    params: PriceMACrossParams,
    market_data: MarketDataPoint,
    signals: TechnicalSignals,
    previous_state: MonitoringRuleState | None,
) -> EvaluationResult:
    """Detect a price / SMA crossover.

    A trigger fires only on the *transition* from one side to the other,
    not while price stays on the same side (no double-trigger).
    """
    try:
        # Select the correct SMA value based on ma_period
        sma_value: float | None = (
            signals.sma_20 if params.ma_period == 20 else signals.sma_50
        )

        if sma_value is None:
            return EvaluationResult(
                triggered=False,
                reason=f"SMA-{params.ma_period} value is not available",
                error=True,
                error_message=f"signals.sma_{params.ma_period} is None",
                evidence={
                    "ticker": signals.ticker,
                    "date": str(signals.date),
                    "ma_period": params.ma_period,
                    "evaluated_at": datetime.now(tz=UTC).isoformat(),
                },
            )

        price = market_data.close

        # Current position: is price above or below the SMA?
        currently_above = price > sma_value

        # Determine previous position from state_data
        prev_above: bool | None = None
        if previous_state is not None and previous_state.state_data:
            prev_above = previous_state.state_data.get("price_above_sma")

        # A crossover is detected when the side changes
        if params.direction == Direction.above:
            # Trigger when price crosses from below to above
            crossed = currently_above and prev_above is not None and not prev_above
        else:
            # Trigger when price crosses from above to below
            crossed = not currently_above and prev_above is not None and prev_above

        direction_label = params.direction.value
        if crossed:
            reason = (
                f"Price {price:.2f} crossed {direction_label} "
                f"SMA-{params.ma_period} ({sma_value:.2f})"
            )
        elif prev_above is None:
            reason = (
                f"First evaluation – price {price:.2f} vs "
                f"SMA-{params.ma_period} ({sma_value:.2f}), "
                f"no previous state to detect crossover"
            )
        else:
            reason = (
                f"Price {price:.2f} vs SMA-{params.ma_period} ({sma_value:.2f}) "
                f"– no new crossover"
            )

        return EvaluationResult(
            triggered=crossed,
            reason=reason,
            current_value=price,
            threshold_value=sma_value,
            evidence={
                "price": price,
                f"sma_{params.ma_period}": sma_value,
                "direction": params.direction.value,
                "currently_above_sma": currently_above,
                "previously_above_sma": prev_above,
                "crossover_detected": crossed,
                "ticker": signals.ticker,
                "date": str(signals.date),
                "evaluated_at": datetime.now(tz=UTC).isoformat(),
            },
        )
    except Exception as exc:  # noqa: BLE001
        return EvaluationResult(
            triggered=False,
            reason="MA cross evaluation failed",
            error=True,
            error_message=str(exc),
            evidence={
                "ticker": signals.ticker,
                "date": str(signals.date),
                "evaluated_at": datetime.now(tz=UTC).isoformat(),
            },
        )
