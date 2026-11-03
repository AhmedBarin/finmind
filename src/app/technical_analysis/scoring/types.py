"""Common result types for indicator family scores."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class FamilyScore:
    """Family score plus its component scores and explanatory notes."""

    score: float | None
    indicator_scores: dict[str, float] = field(default_factory=dict)
    reasons: dict[str, str] = field(default_factory=dict)
    reliable: bool = True

