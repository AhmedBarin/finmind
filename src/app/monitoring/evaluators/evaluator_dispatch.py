"""Evaluator dispatcher – routes RuleParams to the correct evaluator."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.monitoring.evaluators.ma_cross_evaluator import evaluate_ma_cross
from app.monitoring.evaluators.rsi_evaluator import evaluate_rsi_threshold
from app.monitoring.evaluators.score_change_evaluator import evaluate_score_change
from app.monitoring.evaluators.volatility_evaluator import evaluate_volatility
from app.monitoring.schemas.market_data import (
    EvaluationResult,
    MarketDataPoint,
    TechnicalSignals,
)
from app.monitoring.schemas.rules import (
    PriceMACrossParams,
    RSIThresholdParams,
    RuleParams,
    ScoreChangeParams,
    VolatilityThresholdParams,
)

if TYPE_CHECKING:
    from app.monitoring.models.monitoring_rule_state import MonitoringRuleState


def evaluate_rule(
    rule_params: RuleParams,
    market_data: MarketDataPoint,
    signals: TechnicalSignals,
    previous_state: MonitoringRuleState | None = None,
) -> EvaluationResult:
    """Dispatch evaluation to the handler matching *rule_params* type."""
    if isinstance(rule_params, RSIThresholdParams):
        return evaluate_rsi_threshold(rule_params, market_data, signals)

    if isinstance(rule_params, PriceMACrossParams):
        return evaluate_ma_cross(rule_params, market_data, signals, previous_state)

    if isinstance(rule_params, VolatilityThresholdParams):
        return evaluate_volatility(rule_params, market_data, signals)

    if isinstance(rule_params, ScoreChangeParams):
        return evaluate_score_change(rule_params, signals, previous_state)

    return EvaluationResult(
        triggered=False,
        reason=f"Unknown rule type: {type(rule_params).__name__}",
        error=True,
        error_message=f"No evaluator for {type(rule_params).__name__}",
    )
