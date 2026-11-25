from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.explanation import tools as explanation_tools
from app.explanation import service as explanation_service
from app.explanation.constants import ARABIC_RISK_DISCLAIMER
from app.explanation.router import (
    get_explanation_core_service,
    get_explanation_llm,
    router,
)
from app.explanation.service import PreparedExplanationService
from app.explanation.schemas import DataAvailability, EvidenceResult
from app.monitoring.dependencies import get_current_user_id
from app.monitoring.schemas.alerts import AlertResponse, AlertSeverity
from app.recommendation import repository as recommendation_repository
from app.recommendation.dependencies import get_recommendation_session
from app.recommendation.schemas import (
    ConfidenceLevel,
    RecommendationDataQuality,
    RecommendationDecision,
    RecommendationResult,
)
from app.technical_analysis.schemas import TechnicalSnapshotRead
from app.investor.checkpointer import create_memory_checkpointer


AS_OF_DATE = date(2026, 11, 25)


class FakeLLM:
    def __init__(self, outputs):
        self.outputs = list(outputs)

    async def generate_structured(self, *, system_prompt, user_prompt, output_model, model_name=None):
        value = self.outputs.pop(0)
        return output_model.model_validate(value) if isinstance(value, dict) else value


def _snapshot(*, on_date: date) -> TechnicalSnapshotRead:
    return TechnicalSnapshotRead(
        id=uuid4(),
        ticker="COMI",
        date=on_date,
        calculated_at=datetime.combine(on_date, datetime.min.time(), tzinfo=UTC),
        config_version="technical.v1",
        input_hash="fixture-hash",
        data_quality_status="valid",
        rsi=54.2,
        sma_20=None,
        sma_50=None,
        atr=None,
        setup_score=None,
        regime=None,
        risk_label=None,
        indicators={"rsi14": 54.2},
    )


def _app(llm: FakeLLM) -> FastAPI:
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_id] = lambda: uuid4()
    app.dependency_overrides[get_recommendation_session] = lambda: object()
    app.dependency_overrides[get_explanation_llm] = lambda: llm
    return app


class EmptyEvidenceRetriever:
    async def retrieve(self, query):
        return EvidenceResult(status=DataAvailability.NOT_FOUND)


class FakeSession:
    def __init__(self, alert=None):
        self.alert = alert

    async def scalar(self, statement):
        return self.alert

    async def get(self, model, record_id):
        return None


async def _request(app: FastAPI):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        return await client.post(
            "/api/v1/explanations/stock-qa",
            headers={"X-User-ID": "00000000-0000-0000-0000-000000000111"},
            json={
                "question": f"ما قراءة RSI بتاريخ {AS_OF_DATE.isoformat()}؟",
                "tickers": ["comi"],
            },
        )


def _outputs():
    from app.explanation.stock_qa import PlannedToolCall, StockQAToolPlan

    return [
        StockQAToolPlan(
            calls=[
                PlannedToolCall(
                    name="get_technical_snapshot",
                    arguments={"ticker": "COMI", "snapshot_date": AS_OF_DATE.isoformat()},
                )
            ]
        ),
        {
            "answer": "تُظهر اللقطة قراءة RSI14 مقدارها 54.2.",
            "facts": [
                {
                    "label": "rsi",
                    "value": "54.2",
                    "source_tool": "get_technical_snapshot",
                }
            ],
            "limitations": [],
            "disclaimer": ARABIC_RISK_DISCLAIMER,
        },
    ]


@pytest.mark.asyncio
async def test_stock_qa_api_to_tool_to_repository_fixture_e2e(monkeypatch):
    monkeypatch.setattr(explanation_tools, "_today_cairo", lambda: AS_OF_DATE)

    async def get_snapshot(session, ticker, snapshot_date):
        return _snapshot(on_date=snapshot_date)

    monkeypatch.setattr(explanation_tools, "get_snapshot_by_date", get_snapshot)

    response = await _request(_app(FakeLLM(_outputs())))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["tickers"] == ["COMI"]
    assert body["data_date"] == AS_OF_DATE.isoformat()
    assert body["facts"] == [
        {
            "label": "rsi",
            "value": "54.2",
            "source_tool": "get_technical_snapshot",
        }
    ]
    assert body["disclaimer"] == ARABIC_RISK_DISCLAIMER


@pytest.mark.asyncio
async def test_stock_qa_api_to_tool_e2e_preserves_stale_data_warning(monkeypatch):
    monkeypatch.setattr(explanation_tools, "_today_cairo", lambda: AS_OF_DATE)

    async def get_snapshot(session, ticker, snapshot_date):
        return _snapshot(on_date=snapshot_date)

    monkeypatch.setattr(explanation_tools, "get_snapshot_by_date", get_snapshot)

    async def stale_freshness(session, data_date, *, as_of_date):
        return "stale", 3, ["Test fixture marks the snapshot stale."]

    monkeypatch.setattr(explanation_tools, "_freshness", stale_freshness)
    response = await _request(_app(FakeLLM(_outputs())))

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "partial"
    assert any("أقدم من يومي تداول" in item for item in body["limitations"])


@pytest.mark.asyncio
async def test_all_prepared_modes_run_through_api_service_graph_and_shared_contracts(monkeypatch):
    user_id = uuid4()
    recommendation_id = uuid4()
    recommendation = RecommendationResult(
        ticker="COMI",
        trading_date=AS_OF_DATE,
        config_version="recommendation-v1",
        decision=RecommendationDecision.WATCH,
        confidence=ConfidenceLevel.MEDIUM,
        data_quality=RecommendationDataQuality(price_status="valid", last_price_date=AS_OF_DATE),
    )
    audit = SimpleNamespace(
        id=recommendation_id,
        ticker="COMI",
        trading_date=AS_OF_DATE,
        snapshot_id=None,
        config_version="recommendation-v1",
        decision="WATCH",
        confidence="Medium",
        blockers=[],
    )
    async def get_history(*args, **kwargs):
        return [audit]

    async def get_recommendation_by_id(*args, **kwargs):
        return audit

    monkeypatch.setattr(recommendation_repository, "get_recommendation_history", get_history)
    monkeypatch.setattr(recommendation_repository, "get_recommendation_by_id", get_recommendation_by_id)
    alert = AlertResponse(
        id=uuid4(),
        rule_id=uuid4(),
        user_id=user_id,
        ticker="COMI",
        alert_type="rsi",
        severity=AlertSeverity.WARNING,
        reason="RSI crossed the configured threshold",
        evidence={"indicator": "rsi14"},
        current_value=75,
        threshold_value=70,
        created_at=datetime(2026, 11, 24, 12, tzinfo=UTC),
    )
    common = {
        "summary": "شرح موجز",
        "explanation": "هذا شرح مبني على البيانات المقدمة.",
        "facts": [],
        "citation_ids": [],
        "limitations": [],
        "disclaimer": ARABIC_RISK_DISCLAIMER,
    }
    llm = FakeLLM(
        [
            {**common, "decision": "WATCH"},
            common,
            common,
        ]
    )
    core = PreparedExplanationService(
        llm=llm,
        evidence_retriever=EmptyEvidenceRetriever(),
        checkpointer=create_memory_checkpointer(),
    )
    snapshot_record = SimpleNamespace(
        id=uuid4(),
        ticker="COMI",
        date=AS_OF_DATE,
        calculated_at=datetime(2026, 11, 25, tzinfo=UTC),
        config_version="technical.v1",
        input_hash="database-snapshot-fixture",
        data_quality_status="valid",
        rsi=54.2,
        sma_20=None,
        sma_50=None,
        atr=None,
        setup_score=None,
        regime=None,
        risk_label=None,
        input_data={},
        indicators={"rsi14": 54.2},
        scores={},
        quality_flags=[],
    )

    async def get_snapshot_record(*args, **kwargs):
        return snapshot_record

    monkeypatch.setattr(explanation_service, "get_snapshot_by_date", get_snapshot_record)
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_current_user_id] = lambda: user_id
    app.dependency_overrides[get_recommendation_session] = lambda: FakeSession(alert)
    app.dependency_overrides[get_explanation_core_service] = lambda: core
    headers = {"X-User-ID": str(user_id)}

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        recommendation_response = await client.post(
            "/api/v1/explanations/recommendation",
            headers=headers,
            json={"recommendation": recommendation.model_dump(mode="json")},
        )
        alert_response = await client.post(
            "/api/v1/explanations/alert",
            headers=headers,
            json={
                "alert": alert.model_dump(mode="json"),
            },
        )
        follow_up_response = await client.post(
            "/api/v1/explanations/follow-up",
            headers=headers,
            json={
                "question": "Can you explain that again?",
                "subject_type": "recommendation",
                "subject_id": str(recommendation_id),
                "thread_id": "core-modes-thread",
            },
        )

    assert recommendation_response.status_code == 200
    assert recommendation_response.json()["decision"] == "WATCH"
    assert alert_response.status_code == 200
    assert alert_response.json()["explanation_type"] == "alert"
    assert follow_up_response.status_code == 200
    assert follow_up_response.json()["explanation_type"] == "follow_up"


def _async_result(value):
    async def result(*args, **kwargs):
        return value

    return result
