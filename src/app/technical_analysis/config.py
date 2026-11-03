"""Configurable thresholds for technical regime and risk classification."""

from dataclasses import dataclass


# Scoring tables are versioned configuration: a change should be reviewed and
# assigned a new config_version when snapshots are generated.
RSI_ANCHORS: dict[str, tuple[tuple[float, float], ...]] = {
    "trending": (
        (10, 5), (20, 10), (30, 25), (40, 40), (50, 55),
        (60, 75), (70, 85), (80, 70), (90, 55),
    ),
    "ranging": (
        (10, 90), (20, 85), (30, 75), (40, 60), (50, 50),
        (60, 40), (70, 25), (80, 15), (90, 10),
    ),
}

TREND_COMPONENT_WEIGHTS = {
    "close_vs_sma20": 0.30,
    "sma20_vs_sma50": 0.30,
    "sma50_vs_sma200": 0.40,
}
MOMENTUM_COMPONENT_WEIGHTS = {"rsi14": 0.50, "macd_histogram": 0.50}

# Optional scoring refinements and the agreed Volume reliability rule.
OBV_BLENDING_ENABLED = False
MACD_MAGNITUDE_SCALING_ENABLED = False
VOLUME_UNRELIABLE_IF_ZERO_SESSIONS = True
VOLUME_ZERO_CHECK_LOOKBACK_SESSIONS = 20
VOLUME_ABSOLUTE_FLOOR = None  # No absolute volume floor is applied.


@dataclass(frozen=True)
class RegimeThresholds:
    """ADX boundaries; defaults use the spec's examples as provisional values.

    The spec gives 26/23 as an example for entering/leaving trending and does
    not define ranging hysteresis. The 20/22 defaults are therefore provisional
    and should be confirmed before production configuration is frozen.
    """

    ranging_enter: float = 20.0
    ranging_exit: float = 22.0
    trending_exit: float = 23.0
    trending_enter: float = 26.0

    def __post_init__(self) -> None:
        values = (self.ranging_enter, self.ranging_exit, self.trending_exit, self.trending_enter)
        if any(not 0 <= value <= 100 for value in values):
            raise ValueError("ADX thresholds must be between 0 and 100")
        if not self.ranging_enter < self.ranging_exit < self.trending_exit < self.trending_enter:
            raise ValueError("ADX thresholds must be strictly increasing")


@dataclass(frozen=True)
class RiskThresholds:
    """Upper bounds for ATR% percentile risk buckets.

    Buckets include their lower edge and exclude their upper edge:
    [0, 33) low, [33, 66) medium, [66, 90) high, and [90, 100] very high.
    """

    low_max: float = 33.0
    medium_max: float = 66.0
    high_max: float = 90.0

    def __post_init__(self) -> None:
        values = (self.low_max, self.medium_max, self.high_max)
        if any(not 0 <= value <= 100 for value in values):
            raise ValueError("risk percentile thresholds must be between 0 and 100")
        if not self.low_max < self.medium_max < self.high_max:
            raise ValueError("risk thresholds must be strictly increasing")

