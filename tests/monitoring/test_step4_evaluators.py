"""Step 4 – Evaluator unit tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from app.monitoring.evaluators import (
    evaluate_ma_cross,
    evaluate_rsi_threshold,
    evaluate_rule,
    evaluate_score_change,
    evaluate_volatility,
)
from app.monitoring.schemas.market_data import (
    MarketDataPoint,
    TechnicalSignals,
)
from app.monitoring.schemas.rules import (
    Direction,
    PriceMACrossParams,
    RSIThresholdParams,
    ScoreChangeParams,
    VolatilityThresholdParams,
)

# ── Helpers ────────────────────────────────────────────────────────────

NOW = datetime.now(tz=UTC)


def _market(close: float = 150.0) -> MarketDataPoint:
    return MarketDataPoint(
        ticker="AAPL",
        date=date(2024, 6, 15),
        open=148.0,
        high=155.0,
        low=147.0,
        close=close,
        volume=1_000_000,
        updated_at=NOW,
    )


def _signals(
    *,
    rsi: float | None = None,
    sma_20: float | None = None,
    sma_50: float | None = None,
    atr: float | None = None,
    composite_score: float | None = None,
) -> TechnicalSignals:
    return TechnicalSignals(
        ticker="AAPL",
        date=date(2024, 6, 15),
        rsi=rsi,
        sma_20=sma_20,
        sma_50=sma_50,
        atr=atr,
        composite_score=composite_score,
        calculated_at=NOW,
    )


def _state(
    *,
    last_value: float | None = None,
    state_data: dict | None = None,
) -> SimpleNamespace:
    """Lightweight stand-in for MonitoringRuleState (duck-typed)."""
    return SimpleNamespace(
        last_value=last_value,
        state_data=state_data or {},
    )


# ── RSI Evaluator ─────────────────────────────────────────────────────


class TestRSIEvaluator:
    def test_rsi_above_trigger(self):
        params = RSIThresholdParams(threshold=70, direction=Direction.above)
        result = evaluate_rsi_threshold(params, _market(), _signals(rsi=75))
        assert result.triggered is True
        assert result.current_value == 75
        assert result.threshold_value == 70
        assert result.error is False
        assert result.evidence["rsi"] == 75

    def test_rsi_above_no_trigger(self):
        params = RSIThresholdParams(threshold=70, direction=Direction.above)
        result = evaluate_rsi_threshold(params, _market(), _signals(rsi=65))
        assert result.triggered is False
        assert result.error is False

    def test_rsi_below_trigger(self):
        params = RSIThresholdParams(threshold=30, direction=Direction.below)
        result = evaluate_rsi_threshold(params, _market(), _signals(rsi=25))
        assert result.triggered is True
        assert result.current_value == 25

    def test_rsi_below_no_trigger(self):
        params = RSIThresholdParams(threshold=30, direction=Direction.below)
        result = evaluate_rsi_threshold(params, _market(), _signals(rsi=45))
        assert result.triggered is False

    def test_rsi_none_returns_error(self):
        params = RSIThresholdParams(threshold=70, direction=Direction.above)
        result = evaluate_rsi_threshold(params, _market(), _signals(rsi=None))
        assert result.triggered is False
        assert result.error is True
        assert "not available" in result.reason

    def test_rsi_exact_threshold_no_trigger_above(self):
        params = RSIThresholdParams(threshold=70, direction=Direction.above)
        result = evaluate_rsi_threshold(params, _market(), _signals(rsi=70))
        assert result.triggered is False

    def test_rsi_exact_threshold_no_trigger_below(self):
        params = RSIThresholdParams(threshold=30, direction=Direction.below)
        result = evaluate_rsi_threshold(params, _market(), _signals(rsi=30))
        assert result.triggered is False


# ── MA Cross Evaluator ─────────────────────────────────────────────────


class TestMACrossEvaluator:
    def test_crossover_above_detected(self):
        """Price was below SMA-20, now above → trigger."""
        params = PriceMACrossParams(ma_period=20, direction=Direction.above)
        prev = _state(state_data={"price_above_sma": False})
        result = evaluate_ma_cross(
            params, _market(close=155), _signals(sma_20=150), prev
        )
        assert result.triggered is True
        assert result.evidence["crossover_detected"] is True

    def test_already_above_no_double_trigger(self):
        """Price was above SMA-20 and still above → no trigger."""
        params = PriceMACrossParams(ma_period=20, direction=Direction.above)
        prev = _state(state_data={"price_above_sma": True})
        result = evaluate_ma_cross(
            params, _market(close=155), _signals(sma_20=150), prev
        )
        assert result.triggered is False
        assert result.evidence["crossover_detected"] is False

    def test_crossover_below_detected(self):
        """Price was above SMA-50, now below → trigger."""
        params = PriceMACrossParams(ma_period=50, direction=Direction.below)
        prev = _state(state_data={"price_above_sma": True})
        result = evaluate_ma_cross(
            params, _market(close=145), _signals(sma_50=150), prev
        )
        assert result.triggered is True

    def test_first_evaluation_no_trigger(self):
        """No previous state → cannot detect crossover."""
        params = PriceMACrossParams(ma_period=20, direction=Direction.above)
        result = evaluate_ma_cross(
            params, _market(close=155), _signals(sma_20=150), None
        )
        assert result.triggered is False
        assert "First evaluation" in result.reason

    def test_sma_none_returns_error(self):
        params = PriceMACrossParams(ma_period=20, direction=Direction.above)
        result = evaluate_ma_cross(params, _market(), _signals(sma_20=None), None)
        assert result.triggered is False
        assert result.error is True
        assert "not available" in result.reason

    def test_sma_50_used_for_period_50(self):
        """Verify ma_period=50 reads sma_50, not sma_20."""
        params = PriceMACrossParams(ma_period=50, direction=Direction.above)
        prev = _state(state_data={"price_above_sma": False})
        result = evaluate_ma_cross(
            params,
            _market(close=155),
            _signals(sma_20=999, sma_50=150),
            prev,
        )
        assert result.triggered is True
        assert result.evidence["sma_50"] == 150


# ── Volatility Evaluator ──────────────────────────────────────────────


class TestVolatilityEvaluator:
    def test_trigger_above_threshold(self):
        # ATR=6, close=150 → atr_pct=4.0% > 3.0%
        params = VolatilityThresholdParams(atr_pct_threshold=3.0)
        result = evaluate_volatility(params, _market(close=150), _signals(atr=6.0))
        assert result.triggered is True
        assert result.current_value is not None
        assert abs(result.current_value - 4.0) < 0.01
        assert result.evidence["atr_pct"] == 4.0

    def test_no_trigger_below_threshold(self):
        # ATR=3, close=150 → atr_pct=2.0% < 3.0%
        params = VolatilityThresholdParams(atr_pct_threshold=3.0)
        result = evaluate_volatility(params, _market(close=150), _signals(atr=3.0))
        assert result.triggered is False

    def test_atr_none_returns_error(self):
        params = VolatilityThresholdParams(atr_pct_threshold=3.0)
        result = evaluate_volatility(params, _market(), _signals(atr=None))
        assert result.triggered is False
        assert result.error is True

    def test_zero_close_returns_error(self):
        params = VolatilityThresholdParams(atr_pct_threshold=3.0)
        result = evaluate_volatility(params, _market(close=0), _signals(atr=5.0))
        assert result.triggered is False
        assert result.error is True

    def test_exact_threshold_no_trigger(self):
        # ATR=4.5, close=150 → atr_pct=3.0% == threshold → not > so no trigger
        params = VolatilityThresholdParams(atr_pct_threshold=3.0)
        result = evaluate_volatility(params, _market(close=150), _signals(atr=4.5))
        assert result.triggered is False


# ── Score Change Evaluator ─────────────────────────────────────────────


class TestScoreChangeEvaluator:
    def test_score_increase_trigger(self):
        params = ScoreChangeParams(delta_threshold=5)
        prev = _state(last_value=60.0)
        result = evaluate_score_change(params, _signals(composite_score=70.0), prev)
        assert result.triggered is True
        assert result.evidence["delta"] == 10.0

    def test_score_decrease_trigger(self):
        params = ScoreChangeParams(delta_threshold=5)
        prev = _state(last_value=70.0)
        result = evaluate_score_change(params, _signals(composite_score=60.0), prev)
        assert result.triggered is True

    def test_small_change_no_trigger(self):
        params = ScoreChangeParams(delta_threshold=10)
        prev = _state(last_value=60.0)
        result = evaluate_score_change(params, _signals(composite_score=65.0), prev)
        assert result.triggered is False

    def test_direction_above_only(self):
        params = ScoreChangeParams(delta_threshold=5, direction=Direction.above)
        prev = _state(last_value=60.0)
        # Decrease should NOT trigger when direction=above
        result = evaluate_score_change(params, _signals(composite_score=50.0), prev)
        assert result.triggered is False

    def test_direction_below_only(self):
        params = ScoreChangeParams(delta_threshold=5, direction=Direction.below)
        prev = _state(last_value=60.0)
        # Decrease should trigger when direction=below
        result = evaluate_score_change(params, _signals(composite_score=50.0), prev)
        assert result.triggered is True

    def test_no_previous_state(self):
        params = ScoreChangeParams(delta_threshold=5)
        result = evaluate_score_change(params, _signals(composite_score=70.0), None)
        assert result.triggered is False
        assert "First evaluation" in result.reason

    def test_composite_score_none_returns_error(self):
        params = ScoreChangeParams(delta_threshold=5)
        result = evaluate_score_change(
            params, _signals(composite_score=None), _state(last_value=60)
        )
        assert result.triggered is False
        assert result.error is True


# ── Dispatcher ─────────────────────────────────────────────────────────


class TestEvaluateRuleDispatcher:
    def test_dispatches_rsi(self):
        params = RSIThresholdParams(threshold=70, direction=Direction.above)
        result = evaluate_rule(params, _market(), _signals(rsi=75))
        assert result.triggered is True

    def test_dispatches_ma_cross(self):
        params = PriceMACrossParams(ma_period=20, direction=Direction.above)
        prev = _state(state_data={"price_above_sma": False})
        result = evaluate_rule(params, _market(close=155), _signals(sma_20=150), prev)
        assert result.triggered is True

    def test_dispatches_volatility(self):
        params = VolatilityThresholdParams(atr_pct_threshold=3.0)
        result = evaluate_rule(params, _market(close=150), _signals(atr=6.0))
        assert result.triggered is True

    def test_dispatches_score_change(self):
        params = ScoreChangeParams(delta_threshold=5)
        prev = _state(last_value=60.0)
        result = evaluate_rule(params, _market(), _signals(composite_score=70), prev)
        assert result.triggered is True
