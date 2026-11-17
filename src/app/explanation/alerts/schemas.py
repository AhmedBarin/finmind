"""Contracts for monitoring alert explanations.

The input is built from the stored ``alerts`` row, never from a client
payload, so the explanation always describes the alert Monitoring created.
The input contract mirrors the current Monitoring implementation and still
needs the Monitoring team's sign-off (US-009 dependency).
"""

from __future__ import annotations

import math
from datetime import date, datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, ValidationError, field_validator

AlertType = Literal["rsi_threshold", "price_ma_cross", "volatility_threshold", "score_change"]
Severity = Literal["INFO", "WARNING", "CRITICAL"]
AlertGeneration = Literal["llm", "llm_retry", "fallback"]


class AlertInputError(ValueError):
    """The stored alert cannot be explained (unsupported or malformed)."""


class AlertExplanationInput(BaseModel):
    """Validated view of one stored alert (the Alert Input Adapter)."""

    model_config = ConfigDict(frozen=True)

    alert_id: UUID
    ticker: str = Field(min_length=1, max_length=20)
    alert_type: AlertType
    severity: Severity
    reason: str
    observed_value: float | None
    threshold_value: float | None
    observed_at: datetime
    data_date: date | None
    direction: Literal["above", "below"] | None = None
    evidence: dict[str, Any] = Field(default_factory=dict)

    @field_validator("observed_value", "threshold_value")
    @classmethod
    def _finite(cls, value: float | None) -> float | None:
        if value is not None and not math.isfinite(value):
            raise ValueError("must be a finite number")
        return value

    @classmethod
    def from_alert(cls, alert: Any) -> AlertExplanationInput:
        evidence = dict(alert.evidence or {})
        raw_date = evidence.get("date")
        try:
            return cls(
                alert_id=alert.id,
                ticker=alert.ticker.strip().upper(),
                alert_type=alert.alert_type,
                severity=alert.severity,
                reason=alert.reason,
                observed_value=alert.current_value,
                threshold_value=alert.threshold_value,
                observed_at=alert.created_at,
                data_date=date.fromisoformat(raw_date) if raw_date else None,
                direction=evidence.get("direction"),
                evidence=evidence,
            )
        except (ValidationError, ValueError, TypeError) as exc:
            raise AlertInputError(f"alert {alert.id} cannot be explained: {exc}") from None


class AlertKeyFactor(BaseModel):
    model_config = ConfigDict(extra="forbid")

    factor: str = Field(min_length=1, max_length=100)
    value: float | str | None = None
    interpretation_ar: str = Field(min_length=1, max_length=500)


class AlertExplanationDraft(BaseModel):
    """The only part of the explanation the LLM writes."""

    model_config = ConfigDict(extra="forbid")

    summary_ar: str = Field(min_length=1, max_length=500)
    explanation_ar: str = Field(min_length=1, max_length=4000)
    key_factors: list[AlertKeyFactor] = Field(default_factory=list, max_length=10)
    risks_ar: list[str] = Field(default_factory=list, max_length=10)
    limitations_ar: list[str] = Field(default_factory=list, max_length=10)


class SourceRef(BaseModel):
    source_type: Literal["monitoring_alert", "technical_snapshot"]
    source_id: str
    as_of: date | None = None


class AlertExplanationResponse(BaseModel):
    explanation_type: Literal["alert"] = "alert"
    # Copied from the stored alert by code; the LLM never sets these.
    alert_id: UUID
    ticker: str
    alert_type: AlertType
    severity: Severity
    triggered_rule: str
    reason: str
    observed_value: float | None
    threshold_value: float | None
    observed_at: datetime
    data_date: date | None
    # Written by the LLM (validated) or by the safe template.
    summary_ar: str
    explanation_ar: str
    key_factors: list[AlertKeyFactor]
    risks_ar: list[str]
    sources: list[SourceRef]
    limitations_ar: list[str]
    disclaimer_ar: str
    generation: AlertGeneration
