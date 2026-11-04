"""Composite-score change evaluator (stateful)."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from app.monitoring.schemas.market_data import (
    EvaluationResult,
    TechnicalSignals,
)
from app.monitoring.schemas.rules import Direction, ScoreChangeParams

if TYPE_CHECKING:
    from app.monitoring.models.monitoring_rule_state import MonitoringRuleState


def evaluate_score_change(
    params: ScoreChangeParams,
    signals: TechnicalSignals,
    previous_state: MonitoringRuleState | None,
) -> EvaluationResult:
    """Trigger when the composite score moves by at least *delta_threshold*.

    If *direction* is set, only trigger for that direction of change.
    """
    try:
        if signals.composite_score is None:
            return EvaluationResult(
                triggered=False,
                reason="Composite score is not available",
                error=True,
                error_message="signals.composite_score is None",
                evidence={
                    "ticker": signals.ticker,
                    "date": str(signals.date),
                    "evaluated_at": datetime.now(tz=UTC).isoformat(),
                },
            )

        if previous_state is None or previous_state.last_value is None:
            return EvaluationResult(
                triggered=False,
                reason=(
                    f"First evaluation – composite score is "
                    f"{signals.composite_score:.2f}, no previous value to compare"
                ),
                current_value=signals.composite_score,
                threshold_value=params.delta_threshold,
                evidence={
                    "composite_score": signals.composite_score,
                    "previous_score": None,
                    "delta_threshold": params.delta_threshold,
                    "ticker": signals.ticker,
                    "date": str(signals.date),
                    "evaluated_at": datetime.now(tz=UTC).isoformat(),
                },
            )

        previous_score = previous_state.last_value
        delta = signals.composite_score - previous_score
        abs_delta = abs(delta)

        # Direction filter
        if params.direction == Direction.above:
            triggered = delta >= params.delta_threshold
        elif params.direction == Direction.below:
            triggered = delta <= -params.delta_threshold
        else:
            triggered = abs_delta >= params.delta_threshold

        direction_desc = f" ({params.direction.value})" if params.direction else ""
        reason = (
            f"Score changed by {delta:+.2f} (|{abs_delta:.2f}| vs "
            f"threshold {params.delta_threshold}){direction_desc}"
            if triggered
            else f"Score change {delta:+.2f} (|{abs_delta:.2f}|) below "
            f"threshold {params.delta_threshold}{direction_desc}"
        )

        return EvaluationResult(
            triggered=triggered,
            reason=reason,
            current_value=signals.composite_score,
            threshold_value=params.delta_threshold,
            evidence={
                "composite_score": signals.composite_score,
                "previous_score": previous_score,
                "delta": round(delta, 4),
                "abs_delta": round(abs_delta, 4),
                "delta_threshold": params.delta_threshold,
                "direction": params.direction.value if params.direction else None,
                "ticker": signals.ticker,
                "date": str(signals.date),
                "evaluated_at": datetime.now(tz=UTC).isoformat(),
            },
        )
    except Exception as exc:  # noqa: BLE001
        return EvaluationResult(
            triggered=False,
            reason="Score-change evaluation failed",
            error=True,
            error_message=str(exc),
            evidence={
                "ticker": signals.ticker,
                "date": str(signals.date),
                "evaluated_at": datetime.now(tz=UTC).isoformat(),
            },
        )
