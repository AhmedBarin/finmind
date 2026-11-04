"""Regime-weighted setup score for ranking and display only."""

from dataclasses import dataclass
import math
from typing import Mapping

from app.technical_analysis.config import SETUP_SCORE_WEIGHTS
from app.technical_analysis.regime import Regime
from app.technical_analysis.scoring.normalization import clip_score
from app.technical_analysis.scoring.types import FamilyScore


FAMILY_NAMES = ("trend", "momentum", "volume", "support_resistance")


@dataclass(frozen=True)
class SetupScoreResult:
    """Setup score and audit details about weights used for this result."""

    score: float | None
    regime: Regime
    applied_weights: dict[str, float]
    unreliable_families: tuple[str, ...]
    reason: str | None = None


def calculate_setup_score(
    family_scores: Mapping[str, FamilyScore], regime: Regime | str
) -> SetupScoreResult:
    """Combine family scores using regime weights and redistribute missing weight.

    The score is for ranking/display. This function does not decide BUY, WATCH,
    or AVOID. If a family is marked unreliable or has no score, its original
    weight is redistributed proportionally across reliable families.
    """
    current_regime = Regime(regime)
    missing = set(FAMILY_NAMES) - set(family_scores)
    unexpected = set(family_scores) - set(FAMILY_NAMES)
    if missing or unexpected:
        raise ValueError(
            f"family_scores must contain exactly {FAMILY_NAMES}; "
            f"missing={sorted(missing)}, unexpected={sorted(unexpected)}"
        )

    base_weights = SETUP_SCORE_WEIGHTS[current_regime.value]
    reliable_scores: dict[str, float] = {}
    unreliable: list[str] = []
    for name in FAMILY_NAMES:
        family = family_scores[name]
        if not family.reliable or family.score is None:
            unreliable.append(name)
            continue
        value = float(family.score)
        if not math.isfinite(value) or not 0.0 <= value <= 100.0:
            raise ValueError(f"{name} score must be finite and between 0 and 100")
        reliable_scores[name] = value

    original_reliable_weight = sum(base_weights[name] for name in reliable_scores)
    if not reliable_scores or original_reliable_weight == 0:
        return SetupScoreResult(
            score=None,
            regime=current_regime,
            applied_weights={},
            unreliable_families=tuple(unreliable or FAMILY_NAMES),
            reason="No reliable family scores are available.",
        )

    applied_weights = {
        name: base_weights[name] / original_reliable_weight for name in reliable_scores
    }
    combined = sum(reliable_scores[name] * applied_weights[name] for name in reliable_scores)
    return SetupScoreResult(
        score=clip_score(combined),
        regime=current_regime,
        applied_weights=applied_weights,
        unreliable_families=tuple(unreliable),
    )
