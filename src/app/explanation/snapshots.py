"""JSON views of stored technical snapshots shared by explanation modes."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from typing import Any

from app.technical_analysis.models import TechnicalSnapshot

SNAPSHOT_FIELDS = (
    "date",
    "data_quality_status",
    "rsi",
    "sma_20",
    "sma_50",
    "atr",
    "setup_score",
    "regime",
    "risk_label",
)


def json_value(value: Any) -> Any:
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, date):
        return value.isoformat()
    return value


def snapshot_summary(snapshot: TechnicalSnapshot) -> dict[str, Any]:
    """Stored snapshot fields an explanation may cite (raw input window excluded)."""
    data = {name: json_value(getattr(snapshot, name)) for name in SNAPSHOT_FIELDS}
    data["ticker"] = snapshot.ticker
    data["quality_flags"] = list(snapshot.quality_flags or [])
    return data
