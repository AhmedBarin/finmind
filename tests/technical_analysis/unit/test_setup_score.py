import math

import pytest

from app.technical_analysis.regime import Regime
from app.technical_analysis.scoring import FamilyScore, calculate_setup_score


def _families(
    trend: float | None = 80,
    momentum: float | None = 60,
    volume: float | None = 40,
    support_resistance: float | None = 20,
) -> dict[str, FamilyScore]:
    values = {
        "trend": trend,
        "momentum": momentum,
        "volume": volume,
        "support_resistance": support_resistance,
    }
    return {
        name: FamilyScore(score=value, reliable=value is not None)
        for name, value in values.items()
    }


@pytest.mark.parametrize(
    ("regime", "expected_weights"),
    [
        (Regime.TRENDING, {"trend": 0.45, "momentum": 0.25, "volume": 0.15, "support_resistance": 0.15}),
        (Regime.TRANSITION, {"trend": 0.35, "momentum": 0.25, "volume": 0.20, "support_resistance": 0.20}),
        (Regime.RANGING, {"trend": 0.15, "momentum": 0.35, "volume": 0.15, "support_resistance": 0.35}),
    ],
)
def test_setup_score_uses_configured_regime_weights(regime, expected_weights) -> None:
    result = calculate_setup_score(_families(), regime)
    expected = sum(
        score * expected_weights[name]
        for name, score in {
            "trend": 80,
            "momentum": 60,
            "volume": 40,
            "support_resistance": 20,
        }.items()
    )
    assert result.score == expected
    assert result.applied_weights == expected_weights
    assert result.unreliable_families == ()


def test_unreliable_family_weight_is_redistributed_proportionally() -> None:
    families = _families(volume=None)
    result = calculate_setup_score(families, Regime.TRENDING)

    assert result.score == pytest.approx((80 * 45 + 60 * 25 + 20 * 15) / 85)
    assert result.applied_weights == {
        "trend": pytest.approx(45 / 85),
        "momentum": pytest.approx(25 / 85),
        "support_resistance": pytest.approx(15 / 85),
    }
    assert result.unreliable_families == ("volume",)
    assert math.isclose(sum(result.applied_weights.values()), 1.0)


def test_unreliable_flag_excludes_a_family_even_if_it_has_a_score() -> None:
    families = _families()
    families["volume"] = FamilyScore(score=99, reliable=False)
    result = calculate_setup_score(families, Regime.TRANSITION)
    assert "volume" in result.unreliable_families
    assert "volume" not in result.applied_weights


def test_all_unreliable_families_return_no_setup_score() -> None:
    families = {name: FamilyScore(score=None, reliable=False) for name in (
        "trend", "momentum", "volume", "support_resistance"
    )}
    result = calculate_setup_score(families, Regime.RANGING)
    assert result.score is None
    assert result.applied_weights == {}
    assert result.unreliable_families == (
        "trend", "momentum", "volume", "support_resistance"
    )


def test_invalid_or_incomplete_family_scores_are_rejected() -> None:
    with pytest.raises(ValueError, match="missing"):
        calculate_setup_score({"trend": FamilyScore(50)}, Regime.TRENDING)
    with pytest.raises(ValueError, match="between 0 and 100"):
        calculate_setup_score(_families(trend=101), Regime.TRENDING)

