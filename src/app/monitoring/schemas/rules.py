"""Monitoring rule schemas – Pydantic v2."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Annotated, Any, Literal
from uuid import UUID

from pydantic import BaseModel, Field

# ── Enums ──────────────────────────────────────────────────────────────


class RuleType(str, Enum):
    rsi_threshold = "rsi_threshold"
    price_ma_cross = "price_ma_cross"
    volatility_threshold = "volatility_threshold"
    score_change = "score_change"


class Direction(str, Enum):
    above = "above"
    below = "below"


# ── Parameter Schemas (discriminated-union members) ────────────────────


class RSIThresholdParams(BaseModel):
    rule_type: Literal[RuleType.rsi_threshold] = RuleType.rsi_threshold
    threshold: float = Field(..., gt=0, lt=100)
    direction: Direction


class PriceMACrossParams(BaseModel):
    rule_type: Literal[RuleType.price_ma_cross] = RuleType.price_ma_cross
    ma_period: int = Field(..., description="20 or 50")
    direction: Direction


class VolatilityThresholdParams(BaseModel):
    rule_type: Literal[RuleType.volatility_threshold] = RuleType.volatility_threshold
    atr_pct_threshold: float = Field(..., gt=0)


class ScoreChangeParams(BaseModel):
    rule_type: Literal[RuleType.score_change] = RuleType.score_change
    delta_threshold: float = Field(..., gt=0)
    direction: Direction | None = None


# ── Discriminated Union ────────────────────────────────────────────────

RuleParams = Annotated[
    RSIThresholdParams
    | PriceMACrossParams
    | VolatilityThresholdParams
    | ScoreChangeParams,
    Field(discriminator="rule_type"),
]


# ── Request / Response Schemas ─────────────────────────────────────────


class RuleCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    ticker: str = Field(..., min_length=1, max_length=20)
    parameters: RuleParams
    cooldown_minutes: int = Field(default=60, ge=1)


class RuleUpdateRequest(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=200)
    parameters: RuleParams | None = None
    is_active: bool | None = None
    cooldown_minutes: int | None = Field(default=None, ge=1)


class RuleResponse(BaseModel):
    id: UUID
    user_id: UUID
    name: str
    ticker: str
    rule_type: RuleType
    parameters: dict[str, Any]
    is_active: bool
    cooldown_minutes: int
    created_at: datetime
    updated_at: datetime
    deactivated_at: datetime | None = None

    model_config = {"from_attributes": True}
