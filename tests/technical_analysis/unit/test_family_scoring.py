import numpy as np
import pandas as pd
import pytest

from app.technical_analysis.regime import Regime
from app.technical_analysis.scoring import (
    macd_histogram_score,
    momentum_family_score,
    rsi_score,
    support_resistance_score,
    score_state,
    trend_family_score,
    volume_family_score,
    volume_is_reliable,
)
from app.technical_analysis.scoring.normalization import atr_gap_score
from app.technical_analysis.scoring.normalization import ScoreState


def test_atr_gap_score_scales_and_clips() -> None:
    assert atr_gap_score(10, 10, 2) == 50
    assert atr_gap_score(12, 10, 2) == 75
    assert atr_gap_score(8, 10, 2) == 25
    assert atr_gap_score(20, 10, 1) == 100
    assert atr_gap_score(0, 10, 1) == 0


@pytest.mark.parametrize(
    ("score", "expected"),
    [
        (80, ScoreState.STRONGLY_BULLISH),
        (65, ScoreState.BULLISH),
        (45, ScoreState.NEUTRAL),
        (25, ScoreState.BEARISH),
        (24.99, ScoreState.STRONGLY_BEARISH),
    ],
)
def test_score_state_boundaries(score: float, expected: ScoreState) -> None:
    assert score_state(score) is expected


def test_trend_family_uses_30_30_40_weights() -> None:
    result = trend_family_score(close=101, sma20=100, sma50=100, sma200=100, atr14=1)
    assert result.indicator_scores == {
        "close_vs_sma20": 75.0,
        "sma20_vs_sma50": 50.0,
        "sma50_vs_sma200": 50.0,
    }
    assert result.score == 57.5


def test_rsi_interpolates_by_regime_and_clamps_to_anchors() -> None:
    assert rsi_score(15, Regime.TRENDING) == 7.5
    assert rsi_score(15, Regime.RANGING) == 87.5
    assert rsi_score(15, Regime.TRANSITION) == 47.5
    assert rsi_score(0, Regime.TRENDING) == 5.0
    assert rsi_score(100, Regime.RANGING) == 10.0


@pytest.mark.parametrize(
    ("current", "previous", "expected"),
    [(2, 1, 85), (2, 3, 65), (-2, -3, 35), (-2, -1, 15), (0, -1, 50), (2, 2, 50)],
)
def test_macd_histogram_score(current: float, previous: float, expected: float) -> None:
    assert macd_histogram_score(current, previous) == expected


def test_momentum_family_combines_rsi_and_macd_equally() -> None:
    result = momentum_family_score(50, 2, 1, Regime.TRENDING)
    assert result.indicator_scores == {"rsi14": 55.0, "macd_histogram": 85.0}
    assert result.score == 70.0


def test_volume_family_direction_intensity_and_unreliable_state() -> None:
    up = volume_family_score(3, 2, 1, volume_reliable=True)
    down = volume_family_score(3, -2, 1, volume_reliable=True)
    neutral = volume_family_score(3, 0.25, 1, volume_reliable=True)
    unreliable = volume_family_score(3, 2, 1, volume_reliable=False)
    assert up.score == 100.0
    assert down.score == 0.0
    assert neutral.score == 50.0
    assert unreliable.score is None and not unreliable.reliable


def test_volume_reliability_uses_only_zero_sessions_in_recent_20() -> None:
    tiny_positive_volumes = np.full(20, 0.000001)
    assert volume_is_reliable(pd.Series(tiny_positive_volumes))

    zero_in_window = tiny_positive_volumes.copy()
    zero_in_window[-1] = 0.0
    assert not volume_is_reliable(pd.Series(zero_in_window))

    zero_outside_window = np.concatenate(([0.0], tiny_positive_volumes))
    assert volume_is_reliable(pd.Series(zero_outside_window))

    with pytest.raises(ValueError):
        volume_is_reliable(pd.Series([1.0] * 19))


def test_support_resistance_adjustments_and_clipping() -> None:
    near_support = support_resistance_score(100, 99.5, 105, 1, breakout=False, breakdown=False)
    assert near_support.score == 75.0  # near support +15; over 3 ATR to resistance +10
    breakout = support_resistance_score(103, 99, 104, 1, breakout=True, breakdown=False)
    assert breakout.score == 80.0  # baseline + breakout
    breakdown = support_resistance_score(97, 98, 100, 1, breakout=False, breakdown=True)
    assert breakdown.score == 20.0


def test_scores_reject_invalid_inputs() -> None:
    with pytest.raises(ValueError):
        atr_gap_score(1, 2, 0)
    with pytest.raises(ValueError):
        rsi_score(101, Regime.TRENDING)
    with pytest.raises(ValueError):
        volume_family_score(1, 1, 0, volume_reliable=True)
    assert np.isfinite(trend_family_score(10, 10, 10, 10, 1).score)
