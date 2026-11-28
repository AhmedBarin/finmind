"""Tests for the Explanation Agent FastAPI router endpoints."""

from __future__ import annotations

from typing import Any
from uuid import uuid4

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.explanation.constants import ARABIC_RISK_DISCLAIMER
from app.explanation.router import router
from app.explanation.service import ExplanationService, _LLMExplanation, _LLMQAAnswer

# ── Fake LLM & tools ────────────────────────────────────────────────────


class FakeLLM:
    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type,
        model_name: str | None = None,
    ) -> Any:
        if output_model is _LLMExplanation:
            return _LLMExplanation(
                summary="ملخص",
                explanation="شرح تفصيلي",
                facts=["RSI = 55"],
            )
        if output_model is _LLMQAAnswer:
            return _LLMQAAnswer(
                answer="مؤشر RSI عند 55 .",
                facts=[
                    {"label": "RSI", "value": "55", "source_tool": "technical_snapshot"}
                ],
            )
        return None


class FakeSnapshotTool:
    name = "technical_snapshot"

    async def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "tool": self.name,
            "ticker": arguments["ticker"],
            "data_date": "2026-11-20",
            "freshness_seconds": 100,
            "status": "ok",
            "snapshot": {"rsi": 55.0},
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
            "count": 0,
            "prices": [],
        }


class FakeGlossaryTool:
    name = "indicator_glossary"

    async def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return {
            "tool": self.name,
            "data_date": "2026-11-20",
            "freshness_seconds": 0,
            "status": "ok",
            "indicators": {},
        }


# ── Fixtures ─────────────────────────────────────────────────────────────


@pytest.fixture
def test_app() -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.state.explanation_service = ExplanationService(
        llm=FakeLLM(),
        tools=[FakeSnapshotTool(), FakePriceTool(), FakeGlossaryTool()],
    )
    return app


@pytest.fixture
def test_app_no_service() -> FastAPI:
    """App without explanation service initialised."""
    app = FastAPI()
    app.include_router(router)
    return app


# ── Payloads ─────────────────────────────────────────────────────────────


def _recommendation_body() -> dict:
    return {
        "recommendation": {
            "ticker": "COMI",
            "trading_date": "2026-11-20",
            "snapshot_id": str(uuid4()),
            "config_version": "v1",
            "decision": "BUY",
            "reasons": ["Strong RSI"],
            "confidence": "High",
            "setup_score": 72.0,
            "data_quality": {
                "price_status": "valid",
                "last_price_date": "2026-11-20",
            },
        }
    }


def _alert_body() -> dict:
    return {
        "alert": {
            "id": str(uuid4()),
            "rule_id": str(uuid4()),
            "user_id": str(uuid4()),
            "ticker": "COMI",
            "alert_type": "rsi_threshold",
            "severity": "WARNING",
            "reason": "RSI crossed above 70",
            "evidence": {"rsi": 72.5},
            "current_value": 72.5,
            "threshold_value": 70.0,
            "created_at": "2026-11-20T14:00:00Z",
        }
    }


def _follow_up_body() -> dict:
    return {
        "question": "لماذا ارتفع المؤشر؟",
        "subject_type": "recommendation",
        "prior_context": {"ticker": "COMI"},
        "thread_id": "thread-123",
    }


def _qa_body() -> dict:
    return {
        "question": "ما هو مؤشر RSI لسهم COMI؟",
        "tickers": ["COMI"],
    }


# ═══════════════════════════════════════════════════════════════════════════
# Tests
# ═══════════════════════════════════════════════════════════════════════════


class TestRecommendationEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200(self, test_app: FastAPI) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/explanation/recommendation",
                json=_recommendation_body(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["explanation_type"] == "recommendation"
        assert data["ticker"] == "COMI"
        assert data["decision"] == "BUY"
        assert data["disclaimer"] == ARABIC_RISK_DISCLAIMER

    @pytest.mark.asyncio
    async def test_invalid_body_returns_422(self, test_app: FastAPI) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/explanation/recommendation",
                json={},
            )

        assert resp.status_code == 422


class TestAlertEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200(self, test_app: FastAPI) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/explanation/alert",
                json=_alert_body(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["explanation_type"] == "alert"
        assert data["disclaimer"] == ARABIC_RISK_DISCLAIMER


class TestFollowUpEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200(self, test_app: FastAPI) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/explanation/follow-up",
                json=_follow_up_body(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["explanation_type"] == "follow_up"


class TestQAEndpoint:
    @pytest.mark.asyncio
    async def test_returns_200(self, test_app: FastAPI) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/explanation/qa",
                json=_qa_body(),
            )

        assert resp.status_code == 200
        data = resp.json()
        assert data["explanation_type"] == "stock_qa"
        assert data["disclaimer"] == ARABIC_RISK_DISCLAIMER

    @pytest.mark.asyncio
    async def test_empty_tickers_returns_422(self, test_app: FastAPI) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=test_app), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/explanation/qa",
                json={"question": "test", "tickers": []},
            )

        assert resp.status_code == 422


class TestServiceUnavailable:
    @pytest.mark.asyncio
    async def test_returns_503_when_service_missing(
        self, test_app_no_service: FastAPI
    ) -> None:
        async with AsyncClient(
            transport=ASGITransport(app=test_app_no_service), base_url="http://test"
        ) as client:
            resp = await client.post(
                "/api/v1/explanation/recommendation",
                json=_recommendation_body(),
            )

        assert resp.status_code == 503
