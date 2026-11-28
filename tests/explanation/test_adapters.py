from datetime import UTC, datetime
from uuid import uuid4

import pytest

from app.explanation.adapters import adapt_alert, adapt_follow_up, adapt_recommendation
from app.explanation.constants import EXPLANATION_SCHEMA_VERSION
from app.explanation.schemas import (
    AlertExplanationRequest,
    FollowUpRequest,
    RecommendationExplanationRequest,
)
from app.monitoring.schemas.alerts import AlertResponse, AlertSeverity
from app.recommendation.schemas import (
    ConfidenceLevel,
    RecommendationDataQuality,
    RecommendationDecision,
    RecommendationResult,
)
from app.technical_analysis.schemas import TechnicalSnapshotRead


def recommendation() -> RecommendationResult:
    return RecommendationResult(
        ticker="comi",
        trading_date=None,
        config_version=EXPLANATION_SCHEMA_VERSION,
        decision=RecommendationDecision.WATCH,
        confidence=ConfidenceLevel.MEDIUM,
        data_quality=RecommendationDataQuality(
            price_status="valid", last_price_date=None
        ),
    )


def test_recommendation_adapter_preserves_decision_and_flags_missing_snapshot() -> None:
    result = adapt_recommendation(
        RecommendationExplanationRequest(recommendation=recommendation())
    )

    assert result.ticker == "COMI"
    assert result.payload["recommendation"]["decision"] == "WATCH"
    assert result.status.value == "partial"
    assert any("snapshot" in limitation for limitation in result.limitations)


def alert() -> AlertResponse:
    return AlertResponse(
        id=uuid4(),
        rule_id=uuid4(),
        user_id=uuid4(),
        ticker="COMI",
        alert_type="rsi",
        severity=AlertSeverity.WARNING,
        reason="RSI crossed threshold",
        evidence={"indicator": "rsi14"},
        current_value=75,
        threshold_value=70,
        created_at=datetime.now(UTC),
    )


def snapshot(ticker: str = "COMI") -> TechnicalSnapshotRead:
    return TechnicalSnapshotRead(
        id=uuid4(),
        ticker=ticker,
        date=datetime.now(UTC).date(),
        calculated_at=datetime.now(UTC),
        config_version="technical.v1",
        input_hash="hash",
        data_quality_status="valid",
        rsi=None,
        sma_20=None,
        sma_50=None,
        atr=None,
        setup_score=None,
        regime=None,
        risk_label=None,
    )


def test_alert_adapter_requires_matching_snapshot_ticker() -> None:
    request = AlertExplanationRequest(alert=alert(), new_snapshot=snapshot("SWDY"))

    with pytest.raises(ValueError, match="does not match alert ticker"):
        adapt_alert(request)


def test_alert_adapter_flags_missing_old_snapshot() -> None:
    result = adapt_alert(
        AlertExplanationRequest(alert=alert(), new_snapshot=snapshot())
    )

    assert result.ticker == "COMI"
    assert result.status.value == "partial"
    assert any("old" in limitation for limitation in result.limitations)


def test_follow_up_adapter_flags_missing_prior_context() -> None:
    result = adapt_follow_up(
        FollowUpRequest(
            question="Why?", subject_type="recommendation", thread_id="thread-1"
        )
    )

    assert result.status.value == "partial"
    assert result.ticker is None
    assert len(result.limitations) == 2
