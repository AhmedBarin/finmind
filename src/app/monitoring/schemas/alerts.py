"""Monitoring alert schemas – Pydantic v2."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel


class AlertSeverity(str, Enum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class AlertResponse(BaseModel):
    id: UUID
    rule_id: UUID
    user_id: UUID
    ticker: str
    alert_type: str
    severity: AlertSeverity
    reason: str
    evidence: dict[str, Any]
    current_value: float | None = None
    threshold_value: float | None = None
    run_id: UUID | None = None
    created_at: datetime
    acknowledged_at: datetime | None = None

    model_config = {"from_attributes": True}


class AlertAcknowledgeResponse(BaseModel):
    id: UUID
    acknowledged_at: datetime

    model_config = {"from_attributes": True}
