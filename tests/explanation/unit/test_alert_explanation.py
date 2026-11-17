from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio

import app.explanation.router as explanation_router
from app.core.dependencies import get_db_session
from app.explanation.alerts.schemas import AlertExplanationInput, AlertInputError
from app.explanation.alerts.service import (
    NEWS_NOT_SEARCHED_AR,
    NO_LLM_NOTE_AR,
    AlertExplanationService,
)
from app.main import app
from tests.auth_helpers import bearer_headers
from tests.explanation.unit.conftest import ScriptedGenerator, make_snapshot

ALERT_DAY = date(2026, 11, 16)
CREATED = datetime(2026, 11, 16, 14, 30, tzinfo=UTC)

EVIDENCE = {
    "rsi_threshold": ({"rsi": 74.3812, "threshold": 70.0, "direction": "above"}, 74.3812, 70.0),
    "price_ma_cross": (
        {"price": 82.15, "sma_20": 81.456, "direction": "above", "currently_above_sma": True},
        82.15,
        81.456,
    ),
    "volatility_threshold": ({"atr": 2.31, "close": 82.15, "atr_pct": 2.812, "atr_pct_threshold": 2.5}, 2.812, 2.5),
    "score_change": (
        {"composite_score": 64.5, "previous_score": 52.0, "delta": 12.5, "delta_threshold": 10.0},
        64.5,
        10.0,
    ),
}


def make_alert(alert_type: str = "rsi_threshold", **overrides) -> SimpleNamespace:
    evidence, current, threshold = EVIDENCE.get(alert_type, EVIDENCE["rsi_threshold"])
    values = {
        "id": uuid4(),
        "user_id": uuid4(),
        "ticker": "comi.ca",
        "alert_type": alert_type,
        "severity": "INFO",
        "reason": "stored reason",
        "evidence": evidence | {"ticker": "COMI.CA", "date": ALERT_DAY.isoformat()},
        "current_value": current,
        "threshold_value": threshold,
        "created_at": CREATED,
    }
    values.update(overrides)
    return SimpleNamespace(**values)


def _input(alert_type: str = "rsi_threshold", **overrides) -> AlertExplanationInput:
    return AlertExplanationInput.from_alert(make_alert(alert_type, **overrides))


def _snapshots():
    return make_snapshot(day=ALERT_DAY, id=uuid4()), make_snapshot(day=date(2026, 11, 15), id=uuid4(), rsi=68.9)


GOOD = {
    "summary_ar": "ارتفع مؤشر القوة النسبية لسهم COMI.CA فوق الحد المحدد بتاريخ 2026-11-16.",
    "explanation_ar": "أُطلق التنبيه لأن مؤشر القوة النسبية بلغ 74.38 بعد أن كان 68.9 في اللقطة السابقة، متجاوزًا الحد 70.",
    "key_factors": [{"factor": "rsi", "value": 74.3812, "interpretation_ar": "قيمة المؤشر عند التنبيه."}],
    "risks_ar": ["القراءة قد تتغير في الجلسات التالية."],
    "limitations_ar": [],
}


# ── Input adapter ─────────────────────────────────────────────────────


def test_input_adapter_reads_the_stored_alert():
    inp = _input()
    assert inp.ticker == "COMI.CA"
    assert inp.data_date == ALERT_DAY
    assert inp.direction == "above"
    assert inp.observed_value == 74.3812


@pytest.mark.parametrize(
    "overrides",
    [
        {"alert_type": "price_movement"},
        {"severity": "LOUD"},
        {"current_value": float("nan")},
        {"evidence": {"date": "16/11/2026"}},
    ],
)
def test_input_adapter_rejects_unexplainable_alerts(overrides):
    with pytest.raises(AlertInputError):
        AlertExplanationInput.from_alert(make_alert(**overrides))


# ── Service ───────────────────────────────────────────────────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("alert_type", "expected"),
    [
        ("rsi_threshold", ["74.38", "70.00", "أعلى من"]),
        ("price_ma_cross", ["82.15", "81.46", "لـ20 جلسة", "صعودًا"]),
        ("volatility_threshold", ["2.81%", "2.50%"]),
        ("score_change", ["52.00", "64.50", "+12.50", "10.00"]),
    ],
)
async def test_template_per_alert_type(alert_type, expected):
    response = await AlertExplanationService(None).explain(_input(alert_type), *_snapshots())
    assert response.generation == "fallback"
    assert "2026-11-16" in response.explanation_ar
    for text in expected:
        assert text in response.explanation_ar
    assert NO_LLM_NOTE_AR in response.limitations_ar
    assert NEWS_NOT_SEARCHED_AR in response.limitations_ar


@pytest.mark.asyncio
async def test_valid_draft_keeps_alert_facts_from_the_stored_alert():
    llm = ScriptedGenerator(GOOD)
    response = await AlertExplanationService(llm).explain(_input(), *_snapshots())

    assert response.generation == "llm"
    assert response.explanation_type == "alert"
    assert (response.observed_value, response.threshold_value) == (74.3812, 70.0)
    assert response.reason == "stored reason"
    assert response.observed_at == CREATED
    assert response.data_date == ALERT_DAY
    assert response.triggered_rule == "حد مؤشر القوة النسبية"
    assert [s.source_type for s in response.sources] == [
        "monitoring_alert",
        "technical_snapshot",
        "technical_snapshot",
    ]
    assert NEWS_NOT_SEARCHED_AR in response.limitations_ar
    payload = llm.calls[0][1]["content"]
    assert "999.99" not in payload  # raw input window is never sent


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("change", "reason_fragment"),
    [
        ({"explanation_ar": GOOD["explanation_ar"] + " ننصح بالبيع."}, "recommendation language"),
        ({"explanation_ar": "ارتفع المؤشر 74.38 بنسبة 8% خلال يوم."}, "8"),
        ({"summary_ar": "ارتفع مؤشر القوة النسبية فوق الحد."}, "2026-11-16"),
        ({"explanation_ar": "تجاوز المؤشر الحد المحدد 70."}, "observed_value"),
        ({"key_factors": [{"factor": "rsi", "value": 91.0, "interpretation_ar": "x"}]}, "91"),
    ],
)
async def test_invalid_drafts_are_retried_then_fall_back(change, reason_fragment):
    bad = GOOD | change
    llm = ScriptedGenerator(bad, bad)
    response = await AlertExplanationService(llm).explain(_input(), *_snapshots())
    assert response.generation == "fallback"
    assert reason_fragment in llm.calls[1][-1]["content"]
    assert "ننصح" not in response.explanation_ar


@pytest.mark.asyncio
async def test_retry_success():
    bad = GOOD | {"explanation_ar": "ارتفع المؤشر 74.38 بنسبة 8%."}
    llm = ScriptedGenerator(bad, GOOD)
    response = await AlertExplanationService(llm).explain(_input(), *_snapshots())
    assert response.generation == "llm_retry"


@pytest.mark.asyncio
async def test_llm_failure_uses_template(generation_error):
    llm = ScriptedGenerator(generation_error)
    response = await AlertExplanationService(llm).explain(_input(), *_snapshots())
    assert response.generation == "fallback"
    assert NO_LLM_NOTE_AR not in response.limitations_ar


@pytest.mark.asyncio
async def test_missing_snapshots_are_reported():
    response = await AlertExplanationService(None).explain(_input(), None, None)
    assert any("بتاريخ التنبيه" in note for note in response.limitations_ar)
    assert any("سابقة" in note for note in response.limitations_ar)
    assert [s.source_type for s in response.sources] == ["monitoring_alert"]


@pytest.mark.asyncio
async def test_alert_without_data_date_uses_creation_date():
    alert = make_alert(evidence={"rsi": 74.3812, "direction": "above"})
    response = await AlertExplanationService(None).explain(
        AlertExplanationInput.from_alert(alert), None, None
    )
    assert response.data_date is None
    assert "2026-11-16" in response.explanation_ar
    assert any("تاريخ البيانات غير مسجل" in note for note in response.limitations_ar)


# ── Route ─────────────────────────────────────────────────────────────


@pytest_asyncio.fixture
async def client(monkeypatch):
    store: dict = {}

    async def get_alert_for_user(session, alert_id, user_id):
        alert = store.get(alert_id)
        return alert if alert is not None and alert.user_id == user_id else None

    async def get_alert_snapshots(session, ticker, on):
        return _snapshots()

    async def no_session():
        yield None

    monkeypatch.setattr(explanation_router, "get_alert_for_user", get_alert_for_user)
    monkeypatch.setattr(explanation_router, "get_alert_snapshots", get_alert_snapshots)
    app.dependency_overrides[get_db_session] = no_session
    app.dependency_overrides[explanation_router.get_alert_explanation_service] = (
        lambda: AlertExplanationService(None)
    )
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
        http.store = store
        yield http
    app.dependency_overrides.clear()


@pytest.mark.asyncio
async def test_route_explains_own_alert(client):
    alert = make_alert()
    client.store[alert.id] = alert
    response = await client.post(
        f"/api/v1/explanations/alerts/{alert.id}", headers=bearer_headers(alert.user_id)
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["alert_id"] == str(alert.id)
    assert body["ticker"] == "COMI.CA"
    assert body["generation"] == "fallback"


@pytest.mark.asyncio
async def test_route_hides_other_users_alerts(client):
    alert = make_alert()
    client.store[alert.id] = alert
    response = await client.post(
        f"/api/v1/explanations/alerts/{alert.id}", headers=bearer_headers(uuid4())
    )
    assert response.status_code == 404


@pytest.mark.asyncio
async def test_route_rejects_unexplainable_alert(client):
    alert = make_alert(alert_type="price_movement")
    client.store[alert.id] = alert
    response = await client.post(
        f"/api/v1/explanations/alerts/{alert.id}", headers=bearer_headers(alert.user_id)
    )
    assert response.status_code == 422
