from datetime import date, datetime, timezone
from uuid import uuid4

import pytest

from app.explanation.adapters import adapt_alert, adapt_follow_up, adapt_recommendation
from app.explanation.constants import ARABIC_RISK_DISCLAIMER, EXPLANATION_SCHEMA_VERSION
from app.explanation.generator import StructuredGenerator
from app.explanation.schemas import (
    AlertExplanationRequest,
    ExplanationResponse,
    FollowUpRequest,
    RecommendationExplanationRequest,
)
from app.explanation.service import PreparedExplanationService
from app.monitoring.schemas.alerts import AlertResponse, AlertSeverity
from app.recommendation.schemas import (
    ConfidenceLevel,
    RecommendationDataQuality,
    RecommendationDecision,
    RecommendationResult,
)


def make_recommendation(decision=RecommendationDecision.WATCH) -> RecommendationResult:
    return RecommendationResult(
        ticker="COMI",
        trading_date=date(2026, 11, 20),
        snapshot_id=uuid4(),
        config_version=EXPLANATION_SCHEMA_VERSION,
        decision=decision,
        confidence=ConfidenceLevel.MEDIUM,
        data_quality=RecommendationDataQuality(
            price_status="valid", last_price_date=date(2026, 11, 20)
        ),
    )


def make_alert() -> AlertResponse:
    return AlertResponse(
        id=uuid4(),
        rule_id=uuid4(),
        user_id=uuid4(),
        ticker="COMI",
        alert_type="rsi",
        severity=AlertSeverity.WARNING,
        reason="RSI crossed the configured threshold",
        evidence={"indicator": "rsi14"},
        current_value=75,
        threshold_value=70,
        created_at=datetime.now(timezone.utc),
    )


class NoopGenerator:
    async def generate(self, **kwargs):
        raise RuntimeError("not used in sync service contract tests")


def make_service() -> PreparedExplanationService:
    return PreparedExplanationService(generator=StructuredGenerator(NoopGenerator()))


def test_recommendation_fallback_preserves_exact_decision() -> None:
    service = make_service()
    adapted = adapt_recommendation(
        RecommendationExplanationRequest(recommendation=make_recommendation())
    )

    response = service._fallback(adapted, status="unavailable")

    assert response.explanation_type == "recommendation"
    assert response.decision is RecommendationDecision.WATCH
    assert response.disclaimer == ARABIC_RISK_DISCLAIMER


def test_alert_fallback_preserves_alert_mode_and_ticker() -> None:
    service = make_service()
    request = AlertExplanationRequest(alert=make_alert())
    adapted = service._fallback(adapt_alert(request), status="partial")

    assert adapted.explanation_type == "alert"
    assert adapted.ticker == "COMI"
    assert adapted.status == "partial"


def test_follow_up_fallback_keeps_follow_up_mode() -> None:
    service = make_service()
    request = FollowUpRequest(
        question="Why was this decision made?",
        subject_type="recommendation",
        prior_context={"ticker": "COMI", "decision": "WATCH"},
        thread_id="thread-1",
    )
    response = service._fallback(adapt_follow_up(request), status="unavailable")

    assert response.explanation_type == "follow_up"
    assert response.ticker == "COMI"


def test_response_contract_rejects_wrong_explanation_shape() -> None:
    with pytest.raises(ValueError):
        ExplanationResponse.model_validate(
            {"explanation_type": "recommendation", "summary": "missing required fields"}
        )
