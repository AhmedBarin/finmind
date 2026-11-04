import pytest

from app.technical_analysis.config import RegimeThresholds, RiskThresholds
from app.technical_analysis.regime import Regime, classify_regime
from app.technical_analysis.risk import RiskLabel, classify_risk


@pytest.mark.parametrize(
    ("adx14", "expected"),
    [
        (19.9, Regime.RANGING),
        (20.0, Regime.TRANSITION),
        (25.0, Regime.TRANSITION),
        (25.1, Regime.TRENDING),
    ],
)
def test_initial_regime_uses_spec_boundaries(adx14: float, expected: Regime) -> None:
    assert classify_regime(adx14) is expected


def test_regime_hysteresis_keeps_prior_state_inside_band() -> None:
    assert classify_regime(24.0, Regime.TRENDING) is Regime.TRENDING
    assert classify_regime(21.0, Regime.RANGING) is Regime.RANGING
    assert classify_regime(24.0, Regime.TRANSITION) is Regime.TRANSITION


@pytest.mark.parametrize(
    ("percentile", "expected"),
    [
        (0.0, RiskLabel.LOW),
        (32.99, RiskLabel.LOW),
        (33.0, RiskLabel.MEDIUM),
        (65.99, RiskLabel.MEDIUM),
        (66.0, RiskLabel.HIGH),
        (89.99, RiskLabel.HIGH),
        (90.0, RiskLabel.VERY_HIGH),
        (100.0, RiskLabel.VERY_HIGH),
    ],
)
def test_risk_bucket_boundaries(percentile: float, expected: RiskLabel) -> None:
    assert classify_risk(percentile) is expected


def test_missing_values_remain_unknown() -> None:
    assert classify_regime(None) is None
    assert classify_risk(None) is None


def test_thresholds_are_validated_and_overridable() -> None:
    thresholds = RegimeThresholds(trending_enter=28.0)
    assert classify_regime(27.0, Regime.TRANSITION, thresholds) is Regime.TRANSITION
    with pytest.raises(ValueError):
        RiskThresholds(low_max=70.0, medium_max=66.0)

