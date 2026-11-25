from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import UUID, uuid4

import httpx
import pytest
from fastapi import FastAPI

from app.explanation import router as explanation_router_module
from app.explanation.constants import ARABIC_RISK_DISCLAIMER
from app.explanation.intent_splitter import QuestionIntent
from app.explanation.router import get_explanation_core_service, get_explanation_llm, router
from app.explanation.schemas import ExplanationResponse
from app.explanation.stock_qa import PlannedToolCall, StockQAToolPlan
from app.api.error_handlers import safe_unhandled_error
from app.api.middleware import TraceIdMiddleware
from app.monitoring.dependencies import get_current_user_id
from app.recommendation.dependencies import get_recommendation_session
from app.recommendation.schemas import (
    ConfidenceLevel,
    RecommendationDataQuality,
    RecommendationDecision,
    RecommendationResult,
)


USER_ID = UUID("00000000-0000-0000-0000-000000000111")
OTHER_USER_ID = UUID("00000000-0000-0000-0000-000000000222")


class FakeCoreService:
    async def explain_recommendation(self, body, *, user_id):
        return _core_response("recommendation", body.recommendation.decision)

    async def explain_alert(self, body, *, user_id):
        return _core_response("alert")

    async def explain_follow_up(self, body, *, user_id):
        return _core_response("follow_up")


class FailingCoreService(FakeCoreService):
    async def explain_follow_up(self, body, *, user_id):
        raise RuntimeError("sensitive internal detail")


class FakeLLM:
    def __init__(self, output):
        self.output = output

    async def generate_structured(self, *, system_prompt, user_prompt, output_model, model_name=None):
        result = self.output.pop(0)
        return output_model.model_validate(result.model_dump()) if isinstance(result, output_model) else result


class FakeTool:
    def __init__(self, name, status="available"):
        self.name = name
        self.description = name
        self.status = status

    async def ainvoke(self, arguments):
        return {
            "tool": self.name,
            "status": self.status,
            "tickers": ["COMI"],
            "data_date": "2026-11-24" if self.status == "available" else None,
            "freshness_status": "fresh" if self.status == "available" else "not_applicable",
            "payload": {"ticker": "COMI", "indicators": {"rsi14": 54.2}},
            "limitations": [],
        }


def _core_response(kind: str, decision=None) -> ExplanationResponse:
    return ExplanationResponse(
        explanation_type=kind,
        ticker="COMI",
        decision=decision,
        summary="ملخص وصفي",
        explanation="شرح مستند إلى البيانات المقدمة.",
        disclaimer=ARABIC_RISK_DISCLAIMER,
        generated_at=datetime(2026, 11, 25, tzinfo=UTC),
    )


def _app(*, with_core=True, llm=None):
    app = FastAPI()
    app.include_router(router)
    app.add_middleware(TraceIdMiddleware)
    app.add_exception_handler(Exception, safe_unhandled_error)
    app.dependency_overrides[get_current_user_id] = lambda: USER_ID
    app.dependency_overrides[get_recommendation_session] = lambda: None
    app.dependency_overrides[get_explanation_llm] = lambda: llm or FakeLLM([])
    if with_core:
        app.dependency_overrides[get_explanation_core_service] = lambda: FakeCoreService()
    return app


async def _post(app, path: str, payload=None, *, headers=None):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app, raise_app_exceptions=False),
        base_url="http://test",
    ) as client:
        return await client.post(path, json=payload, headers=headers or {})


def _recommendation_payload():
    return {
        "recommendation": {
            "ticker": "COMI",
            "trading_date": "2026-11-24",
            "config_version": "recommendation-v1",
            "decision": "WATCH",
            "confidence": "Medium",
            "data_quality": {"price_status": "valid", "last_price_date": "2026-11-24"},
        }
    }


def _alert_payload(user_id=USER_ID):
    return {
        "alert": {
            "id": str(uuid4()),
            "rule_id": str(uuid4()),
            "user_id": str(user_id),
            "ticker": "COMI",
            "alert_type": "rsi",
            "severity": "WARNING",
            "reason": "RSI crossed threshold",
            "evidence": {"indicator": "rsi14"},
            "current_value": 75,
            "threshold_value": 70,
            "created_at": "2026-11-24T12:00:00Z",
        }
    }


@pytest.mark.asyncio
async def test_typed_mode_endpoints_delegate_and_preserve_recommendation_decision():
    app = _app()
    response = await _post(app, "/api/v1/explanations/recommendation", _recommendation_payload())

    assert response.status_code == 200
    assert response.json()["explanation_type"] == "recommendation"
    assert response.json()["decision"] == "WATCH"


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("path", "payload", "expected_type"),
    [
        ("/api/v1/explanations/alert", _alert_payload(), "alert"),
        (
            "/api/v1/explanations/follow-up",
            {"question": "Why?", "subject_type": "stock_qa", "thread_id": "thread-1"},
            "follow_up",
        ),
    ],
)
async def test_core_mode_endpoints_return_their_typed_response(path, payload, expected_type):
    response = await _post(_app(), path, payload)

    assert response.status_code == 200
    assert response.json()["explanation_type"] == expected_type


@pytest.mark.asyncio
async def test_alert_endpoint_enforces_user_ownership():
    response = await _post(
        _app(), "/api/v1/explanations/alert", _alert_payload(OTHER_USER_ID)
    )

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_core_routes_return_safe_unavailable_when_core_service_is_absent():
    response = await _post(
        _app(with_core=False), "/api/v1/explanations/follow-up", {
            "question": "Why?",
            "subject_type": "stock_qa",
            "thread_id": "thread-1",
        }
    )

    assert response.status_code == 503
    assert response.json()["detail"] == "Explanation service is not configured"


@pytest.mark.asyncio
async def test_core_route_hides_internal_errors():
    app = _app()
    app.dependency_overrides[get_explanation_core_service] = lambda: FailingCoreService()
    response = await _post(
        app,
        "/api/v1/explanations/follow-up",
        {"question": "Why?", "subject_type": "stock_qa", "thread_id": "thread-1"},
    )

    assert response.status_code == 500
    assert response.json()["detail"] == "Internal server error"
    assert "sensitive internal detail" not in response.text


@pytest.mark.asyncio
async def test_missing_authentication_is_rejected():
    app = FastAPI()
    app.include_router(router)
    app.dependency_overrides[get_recommendation_session] = lambda: None
    app.dependency_overrides[get_explanation_llm] = lambda: FakeLLM([])

    response = await _post(
        app,
        "/api/v1/explanations/stock-qa",
        {"question": "ما قيمة RSI؟", "tickers": ["COMI"]},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_question_rejects_invalid_ticker_input():
    response = await _post(
        _app(),
        "/api/v1/explanations/question",
        {"question": "What is RSI?", "tickers": ["COMI", "COMI"]},
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_stock_qa_endpoint_uses_allowlisted_tools_and_returns_typed_response(monkeypatch):
    monkeypatch.setattr(
        explanation_router_module,
        "build_stock_qa_tools",
        lambda *, session: [FakeTool(name) for name in sorted({
            "get_technical_snapshot", "get_snapshot_history", "get_price_history",
            "compare_snapshots", "get_indicator_glossary",
        })],
    )
    plan = StockQAToolPlan(
        calls=[PlannedToolCall(name="get_technical_snapshot", arguments={"ticker": "COMI", "snapshot_date": date(2026, 11, 24)})]
    )
    draft = {
        "answer": "تُظهر البيانات قراءة RSI مقدارها 54.2.",
        "facts": [{"label": "RSI14", "value": "54.2", "source_tool": "get_technical_snapshot"}],
        "limitations": [],
        "disclaimer": ARABIC_RISK_DISCLAIMER,
    }
    response = await _post(
        _app(llm=FakeLLM([plan, draft])),
        "/api/v1/explanations/stock-qa",
        {"question": "ما قيمة RSI؟", "tickers": ["comi"]},
    )

    assert response.status_code == 200
    assert response.json()["explanation_type"] == "stock_qa"
    assert response.json()["tickers"] == ["COMI"]


@pytest.mark.asyncio
async def test_stock_qa_endpoint_preserves_missing_data_state(monkeypatch):
    def fake_tools(*, session):
        return [
            FakeTool(name, status="not_found" if name == "get_technical_snapshot" else "available")
            for name in sorted({
                "get_technical_snapshot", "get_snapshot_history", "get_price_history",
                "compare_snapshots", "get_indicator_glossary",
            })
        ]

    monkeypatch.setattr(explanation_router_module, "build_stock_qa_tools", fake_tools)
    plan = StockQAToolPlan(
        calls=[PlannedToolCall(name="get_technical_snapshot", arguments={"ticker": "COMI", "snapshot_date": date(2026, 11, 24)})]
    )
    draft = {
        "answer": "لم تتوفر لقطة فنية مطابقة.",
        "facts": [],
        "limitations": [],
        "disclaimer": ARABIC_RISK_DISCLAIMER,
    }
    response = await _post(
        _app(llm=FakeLLM([plan, draft])),
        "/api/v1/explanations/stock-qa",
        {"question": "ما البيانات؟", "tickers": ["COMI"]},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "not_found"
    assert any("لم تتوفر" in item for item in response.json()["limitations"])


@pytest.mark.asyncio
async def test_question_endpoint_returns_clarification_for_ambiguous_question():
    response = await _post(
        _app(),
        "/api/v1/explanations/question",
        {"question": "Hello there", "tickers": ["comi"]},
    )

    assert response.status_code == 200
    assert response.json()["intent"] == QuestionIntent.AMBIGUOUS.value
    assert response.json()["clarification"]
    assert response.json()["recommendations"] == []


@pytest.mark.asyncio
async def test_mixed_question_routes_to_stock_qa_and_recommendation_engine(monkeypatch):
    monkeypatch.setattr(
        explanation_router_module,
        "build_stock_qa_tools",
        lambda *, session: [FakeTool(name) for name in sorted({
            "get_technical_snapshot", "get_snapshot_history", "get_price_history",
            "compare_snapshots", "get_indicator_glossary",
        })],
    )
    recommendation = RecommendationResult(
        ticker="COMI",
        trading_date=date(2026, 11, 24),
        config_version="recommendation-v1",
        decision=RecommendationDecision.WATCH,
        confidence=ConfidenceLevel.MEDIUM,
        data_quality=RecommendationDataQuality(price_status="valid", last_price_date=date(2026, 11, 24)),
    )
    audit = SimpleNamespace(id=uuid4(), created_at=datetime(2026, 11, 25, tzinfo=UTC))
    monkeypatch.setattr(explanation_router_module, "load_recommendation_inputs", _async_value(object()))
    monkeypatch.setattr(explanation_router_module, "evaluate_decision", lambda inputs: object())
    monkeypatch.setattr(explanation_router_module, "build_recommendation_result", lambda inputs, evaluation: recommendation)
    monkeypatch.setattr(explanation_router_module.recommendation_repository, "save_recommendation_log", _async_value(audit))
    plan = StockQAToolPlan(
        calls=[PlannedToolCall(name="get_technical_snapshot", arguments={"ticker": "COMI", "snapshot_date": date(2026, 11, 24)})]
    )
    draft = {
        "answer": "تُظهر البيانات قراءة RSI مقدارها 54.2.",
        "facts": [{"label": "RSI14", "value": "54.2", "source_tool": "get_technical_snapshot"}],
        "limitations": [],
        "disclaimer": ARABIC_RISK_DISCLAIMER,
    }
    response = await _post(
        _app(llm=FakeLLM([plan, draft])),
        "/api/v1/explanations/question",
        {"question": "What is RSI and should I buy COMI?", "tickers": ["COMI"]},
    )

    assert response.status_code == 200
    assert response.json()["intent"] == QuestionIntent.MIXED.value
    assert response.json()["stock_qa"]["explanation_type"] == "stock_qa"
    assert response.json()["recommendations"][0]["result"]["decision"] == "WATCH"


def test_openapi_exposes_typed_routes_for_all_four_modes():
    app = _app()
    paths = app.openapi()["paths"]

    assert "/api/v1/explanations/recommendation" in paths
    assert "/api/v1/explanations/alert" in paths
    assert "/api/v1/explanations/follow-up" in paths
    assert "/api/v1/explanations/stock-qa" in paths
    assert paths["/api/v1/explanations/stock-qa"]["post"]["responses"]["200"]["content"]["application/json"]["schema"]["$ref"].endswith("StockQAResponse")


def _async_value(value):
    async def return_value(*args, **kwargs):
        return value

    return return_value
