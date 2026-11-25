"""Adapters from upstream module payloads into Explanation Agent context."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

from app.explanation.schemas import (
    AlertExplanationRequest,
    DataAvailability,
    ExplanationMode,
    FollowUpRequest,
    RecommendationExplanationRequest,
)


@dataclass(frozen=True)
class AdaptedInput:
    """Validated, mode-neutral input for the explanation graph."""

    mode: ExplanationMode
    ticker: str | None
    as_of: date | None
    payload: dict[str, Any]
    status: DataAvailability
    limitations: tuple[str, ...] = ()


def adapt_recommendation(request: RecommendationExplanationRequest) -> AdaptedInput:
    recommendation = request.recommendation
    limitations: list[str] = []
    status = DataAvailability.AVAILABLE

    if recommendation.trading_date is None:
        limitations.append("Recommendation has no trading date.")
        status = DataAvailability.PARTIAL
    if recommendation.data_quality.price_status != "valid":
        limitations.append(
            f"Recommendation price data is {recommendation.data_quality.price_status}."
        )
        status = (
            DataAvailability.UNAVAILABLE
            if recommendation.data_quality.price_status == "unavailable"
            else DataAvailability.STALE
        )
    if recommendation.snapshot_id is None:
        limitations.append("No technical snapshot ID is attached to the recommendation.")
        if status is DataAvailability.AVAILABLE:
            status = DataAvailability.PARTIAL

    return AdaptedInput(
        mode=ExplanationMode.RECOMMENDATION,
        ticker=recommendation.ticker.strip().upper(),
        as_of=recommendation.trading_date,
        payload={
            "recommendation": recommendation.model_dump(mode="json"),
            "language": request.language.value,
            "thread_id": request.thread_id,
        },
        status=status,
        limitations=tuple(limitations),
    )


def adapt_alert(request: AlertExplanationRequest) -> AdaptedInput:
    alert = request.alert
    ticker = alert.ticker.strip().upper()
    limitations: list[str] = []
    status = DataAvailability.AVAILABLE

    for label, snapshot in (("old", request.old_snapshot), ("new", request.new_snapshot)):
        if snapshot is None:
            limitations.append(f"The {label} technical snapshot is unavailable.")
            status = DataAvailability.PARTIAL
        elif snapshot.ticker.strip().upper() != ticker:
            raise ValueError(f"{label} snapshot ticker does not match alert ticker")
        elif snapshot.data_quality_status != "valid":
            limitations.append(
                f"The {label} technical snapshot is {snapshot.data_quality_status}."
            )
            status = DataAvailability.STALE

    if alert.current_value is None:
        limitations.append("Alert current value is unavailable.")
        status = DataAvailability.PARTIAL
    if alert.threshold_value is None:
        limitations.append("Alert threshold value is unavailable.")
        status = DataAvailability.PARTIAL

    return AdaptedInput(
        mode=ExplanationMode.ALERT,
        ticker=ticker,
        as_of=alert.created_at.date(),
        payload={
            "alert": alert.model_dump(mode="json"),
            "old_snapshot": request.old_snapshot.model_dump(mode="json")
            if request.old_snapshot
            else None,
            "new_snapshot": request.new_snapshot.model_dump(mode="json")
            if request.new_snapshot
            else None,
            "language": request.language.value,
            "thread_id": request.thread_id,
        },
        status=status,
        limitations=tuple(limitations),
    )


def adapt_follow_up(request: FollowUpRequest) -> AdaptedInput:
    limitations: list[str] = []
    status = DataAvailability.AVAILABLE
    if not request.prior_context:
        limitations.append("No prior explanation context was supplied.")
        status = DataAvailability.PARTIAL

    authorized_subject = request.prior_context.get("authorized_subject")
    authorized_subject = authorized_subject if isinstance(authorized_subject, dict) else {}
    raw_ticker = request.prior_context.get("ticker") or authorized_subject.get("ticker")
    ticker = raw_ticker.strip().upper() if isinstance(raw_ticker, str) and raw_ticker.strip() else None
    if ticker is None:
        limitations.append("The prior context has no ticker.")
        status = DataAvailability.PARTIAL

    raw_date = (
        request.prior_context.get("data_date")
        or request.prior_context.get("trading_date")
        or authorized_subject.get("data_date")
        or authorized_subject.get("trading_date")
    )
    as_of = raw_date
    if isinstance(raw_date, str):
        try:
            as_of = date.fromisoformat(raw_date)
        except ValueError:
            limitations.append("The prior context has an invalid data date.")
            status = DataAvailability.PARTIAL
    return AdaptedInput(
        mode=ExplanationMode.FOLLOW_UP,
        ticker=ticker,
        as_of=as_of if isinstance(as_of, date) else None,
        payload={
            "question": request.question,
            "subject_type": request.subject_type,
            "subject_id": str(request.subject_id) if request.subject_id else None,
            "prior_context": request.prior_context,
            "language": request.language.value,
            "thread_id": request.thread_id,
        },
        status=status,
        limitations=tuple(limitations),
    )
