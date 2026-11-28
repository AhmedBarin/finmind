"""Tests for the Explanation Service orchestrator."""

from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest

from app.explanation.constants import ARABIC_RISK_DISCLAIMER
from app.explanation.schemas import (
    AlertExplanationRequest,
    ExplanationResponse,
    FollowUpRequest,
    RecommendationExplanationRequest,
    StockQARequest,
    StockQAResponse,
)
from app.explanation.service import ExplanationService, _LLMExplanation, _LLMQAAnswer
from app.monitoring.schemas.alerts import AlertResponse, AlertSeverity
from app.recommendation.schemas import (
    ConfidenceLevel,
    RecommendationDataQuality,
    RecommendationDecision,
    RecommendationResult,
)

# ── Fake LLM ─────────────────────────────────────────────────────────────


class FakeLLM:
    """Deterministic LLM stub for testing."""

    def __init__(self, response: Any = None) -> None:
        self._response = response
        self.calls: list[dict[str, Any]] = []

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type,
        model_name: str | None = None,
    ) -> Any:
        self.calls.append(
            {
                "system_prompt": system_prompt,
                "user_prompt": user_prompt,
                "output_model": output_model,
            }
        )
        if self._response is not None:
            return self._response
        if output_model is _LLMExplanation:
            return _LLMExplanation(
                summary="ملخص تحليلي للسهم",
                explanation="شرح تفصيلي للبيانات الفنية",
                facts=["RSI = 55"],
            )
        if output_model is _LLMQAAnswer:
            return _LLMQAAnswer(
                answer="مؤشر RSI حالياً عند 55 مما يشير إلى وضع محايد.",
                facts=[
                    {"label": "RSI", "value": "55", "source_tool": "technical_snapshot"}
                ],
            )
        return None


class AdvisoryLLM:
    """LLM stub that returns recommendation language."""

    def __init__(self) -> None:
        self.call_count = 0

    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type,
        model_name: str | None = None,
    ) -> Any:
        self.call_count += 1
        if output_model is _LLMQAAnswer:
            return _LLMQAAnswer(
                answer="يجب عليك شراء السهم فوراً",
                facts=[],
            )
        return _LLMExplanation(
            summary="ملخص",
            explanation="شرح",
            facts=[],
        )


# ── Fake tools ───────────────────────────────────────────────────────────


class FakeSnapshotTool:
    name = "technical_snapshot"

    async def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "tool": self.name,
            "ticker": arguments["ticker"],
            "data_date": "2026-11-20",
            "freshness_seconds": 100,
            "status": "ok",
            "snapshot": {"rsi": 55.0, "sma_20": 42.5, "setup_score": 72.0},
        }


class FakePriceTool:
    name = "price_history"

    async def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "tool": self.name,
            "ticker": arguments["ticker"],
            "data_date": "2026-11-20",
            "freshness_seconds": 100,
            "status": "ok",
            "count": 1,
            "prices": [{"close": 43.0, "volume": 1500000}],
        }


class FakeGlossaryTool:
    name = "indicator_glossary"

    async def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "tool": self.name,
            "data_date": "2026-11-20",
            "freshness_seconds": 0,
            "status": "ok",
            "indicators": {"RSI": {"name_ar": "مؤشر القوة النسبية"}},
        }


# ── Helpers ──────────────────────────────────────────────────────────────


def _make_recommendation() -> RecommendationResult:
    return RecommendationResult(
        ticker="COMI",
        trading_date=date(2026, 11, 20),
        snapshot_id=uuid4(),
        config_version="v1",
        decision=RecommendationDecision.BUY,
        reasons=["Strong RSI", "Above SMA-20"],
        confidence=ConfidenceLevel.HIGH,
        setup_score=72.0,
        data_quality=RecommendationDataQuality(
            price_status="valid",
            last_price_date=date(2026, 11, 20),
        ),
    )


def _make_alert() -> AlertResponse:
    return AlertResponse(
        id=uuid4(),
        rule_id=uuid4(),
        user_id=uuid4(),
        ticker="COMI",
        alert_type="rsi_threshold",
        severity=AlertSeverity.WARNING,
        reason="RSI crossed above 70",
        evidence={"rsi": 72.5},
        current_value=72.5,
        threshold_value=70.0,
        created_at=datetime(2026, 11, 20, 14, 0, tzinfo=UTC),
    )


def _make_service(llm: Any = None) -> ExplanationService:
    return ExplanationService(
        llm=llm or FakeLLM(),
        tools=[FakeSnapshotTool(), FakePriceTool(), FakeGlossaryTool()],
    )


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestExplainRecommendation:
    @pytest.mark.asyncio
    async def test_produces_response_with_disclaimer(self) -> None:
        service = _make_service()
        request = RecommendationExplanationRequest(
            recommendation=_make_recommendation(),
        )

        result = await service.explain_recommendation(request)

        assert isinstance(result, ExplanationResponse)
        assert result.explanation_type == "recommendation"
        assert result.ticker == "COMI"
        assert result.decision == RecommendationDecision.BUY
        assert result.disclaimer == ARABIC_RISK_DISCLAIMER
        assert result.summary
        assert result.explanation

    @pytest.mark.asyncio
    async def test_preserves_decision_immutably(self) -> None:
        service = _make_service()
        rec = _make_recommendation()
        request = RecommendationExplanationRequest(recommendation=rec)

        result = await service.explain_recommendation(request)

        # Decision must come through unchanged
        assert result.decision == rec.decision


class TestExplainAlert:
    @pytest.mark.asyncio
    async def test_produces_response_with_disclaimer(self) -> None:
        service = _make_service()
        request = AlertExplanationRequest(alert=_make_alert())

        result = await service.explain_alert(request)

        assert isinstance(result, ExplanationResponse)
        assert result.explanation_type == "alert"
        assert result.ticker == "COMI"
        assert result.disclaimer == ARABIC_RISK_DISCLAIMER


class TestFollowUp:
    @pytest.mark.asyncio
    async def test_produces_response_with_context(self) -> None:
        service = _make_service()
        request = FollowUpRequest(
            question="لماذا ارتفع المؤشر؟",
            subject_type="recommendation",
            prior_context={"ticker": "COMI", "data_date": "2026-11-20"},
            thread_id="thread-123",
        )

        result = await service.handle_follow_up(request)

        assert isinstance(result, ExplanationResponse)
        assert result.explanation_type == "follow_up"
        assert result.disclaimer == ARABIC_RISK_DISCLAIMER


class TestStockQA:
    @pytest.mark.asyncio
    async def test_basic_qa_response(self) -> None:
        service = _make_service()
        request = StockQARequest(
            question="ما هو مؤشر RSI لسهم COMI؟",
            tickers=["COMI"],
        )

        result = await service.answer_stock_qa(request)

        assert isinstance(result, StockQAResponse)
        assert result.explanation_type == "stock_qa"
        assert result.disclaimer == ARABIC_RISK_DISCLAIMER
        assert result.tickers == ["COMI"]

    @pytest.mark.asyncio
    async def test_advisory_question_returns_safe_fallback(self) -> None:
        service = _make_service()
        request = StockQARequest(
            question="هل أشتري سهم COMI؟",
            tickers=["COMI"],
        )

        result = await service.answer_stock_qa(request)

        assert "لا يمكنني" in result.answer

    @pytest.mark.asyncio
    async def test_recommendation_in_llm_response_triggers_retry_and_fallback(
        self,
    ) -> None:
        llm = AdvisoryLLM()
        service = _make_service(llm=llm)
        request = StockQARequest(
            question="ما هو مؤشر RSI لسهم COMI؟",
            tickers=["COMI"],
        )

        result = await service.answer_stock_qa(request)

        # LLM was called twice (original + retry), then fell back
        assert llm.call_count == 2
        assert "لا يمكنني" in result.answer

    @pytest.mark.asyncio
    async def test_data_date_and_freshness_populated(self) -> None:
        service = _make_service()
        request = StockQARequest(
            question="ما هو مؤشر RSI لسهم COMI؟",
            tickers=["COMI"],
        )

        result = await service.answer_stock_qa(request)

        assert result.data_date is not None
        assert result.freshness_seconds is not None
