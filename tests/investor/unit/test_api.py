"""Investor Agent API tests: HITL gate, edits, ownership, and resume.

The graph uses an in-memory checkpointer and repository calls are replaced by
an in-memory fake, so these tests need neither PostgreSQL nor an LLM.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal
from typing import Any
from unittest.mock import AsyncMock
from uuid import UUID, uuid4

import httpx
import pytest
import pytest_asyncio

from app.investor import repository, router as investor_router
from app.investor.checkpointer import create_memory_checkpointer
from app.investor.graph import build_interview_graph
from app.investor.models import InvestorProfile
from app.investor.schemas import (
    ConstraintsUpdateRequest,
    InvestorProfileConfirmRequest,
    InvestorProfilePayload,
    compute_gating_parameters,
)
from app.main import app

BASE = "http://test/api/v1/investor"

INTERVIEW = [
    "هدفي تنمية رأس المال واستبعاد قطاع التبغ",
    "متوسط الأجل من 1 إلى 6 أشهر",
    "الأموال فائضة عن حاجتي وأتحمل تقلبات معقولة بشكل معتدل",
    "خبرتي متوسطة",
]


class FakeProfileStore:
    """In-memory stand-in for the profile repository functions."""

    def __init__(self) -> None:
        self.profiles: dict[UUID, InvestorProfile] = {}

    async def get_active_profile(self, session: Any, user_id: UUID) -> InvestorProfile | None:
        return self.profiles.get(user_id)

    async def get_active_profile_payload(self, session: Any, user_id: UUID):
        profile = self.profiles.get(user_id)
        return InvestorProfilePayload.model_validate(profile) if profile else None

    async def confirm_and_activate_profile(
        self, session: Any, user_id: UUID, confirmation: InvestorProfileConfirmRequest, **_: Any
    ) -> InvestorProfile:
        previous = self.profiles.get(user_id)
        liquidity, atr = compute_gating_parameters(confirmation.risk_profile)
        now = datetime.now(UTC)
        profile = InvestorProfile(
            id=uuid4(),
            user_id=user_id,
            risk_profile=confirmation.risk_profile.value,
            investment_horizon=confirmation.investment_horizon.value,
            investment_goal=confirmation.investment_goal.value,
            investment_experience=confirmation.investment_experience.value,
            liquidity_floor_pct=Decimal(str(liquidity)),
            max_atr_pctl_cap=Decimal(str(atr)),
            excluded_sectors=list(confirmation.excluded_sectors),
            excluded_tickers=list(confirmation.excluded_tickers),
            preferred_sectors=list(confirmation.preferred_sectors),
            is_active=True,
            profile_version=(previous.profile_version + 1) if previous else 1,
            confirmed_at=now,
            last_reviewed_at=now,
        )
        self.profiles[user_id] = profile
        return profile

    async def update_profile_constraints(
        self, session: Any, user_id: UUID, update: ConstraintsUpdateRequest, **_: Any
    ) -> InvestorProfile | None:
        profile = self.profiles.get(user_id)
        if profile is None:
            return None
        if update.excluded_tickers is not None:
            profile.excluded_tickers = list(update.excluded_tickers)
        if update.excluded_sectors is not None:
            profile.excluded_sectors = list(update.excluded_sectors)
        if update.preferred_sectors is not None:
            profile.preferred_sectors = list(update.preferred_sectors)
        profile.profile_version += 1
        return profile


class FakeMemory:
    def __init__(self) -> None:
        self.remembered: list[Any] = []

    async def remember(self, session: Any, user_id: UUID, preference: Any) -> Any:
        self.remembered.append((user_id, preference))
        return preference

    async def recall(self, session: Any, user_id: UUID, *, validated_only: bool = False) -> list[Any]:
        return []


@pytest.fixture
def store(monkeypatch: pytest.MonkeyPatch) -> FakeProfileStore:
    fake = FakeProfileStore()
    for name in (
        "get_active_profile",
        "get_active_profile_payload",
        "confirm_and_activate_profile",
        "update_profile_constraints",
    ):
        monkeypatch.setattr(repository, name, getattr(fake, name))
    return fake


@pytest.fixture
def memory() -> FakeMemory:
    return FakeMemory()


@pytest_asyncio.fixture
async def client(store: FakeProfileStore, memory: FakeMemory):
    graph = build_interview_graph(checkpointer=create_memory_checkpointer())
    db_session = AsyncMock()

    async def _db():
        yield db_session

    app.dependency_overrides[investor_router.get_db_session] = _db
    app.dependency_overrides[investor_router.get_interview_graph] = lambda: graph
    app.dependency_overrides[investor_router.get_preference_memory] = lambda: memory
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=BASE
    ) as http:
        yield http
    app.dependency_overrides.clear()


def _headers(user_id: UUID) -> dict[str, str]:
    return {"X-User-ID": str(user_id)}


async def _run_interview(client: httpx.AsyncClient, user_id: UUID, session_id: UUID) -> dict:
    data: dict = {}
    for message in INTERVIEW:
        resp = await client.post(
            "/interview/message",
            json={"session_id": str(session_id), "message": message},
            headers=_headers(user_id),
        )
        assert resp.status_code == 200, resp.text
        data = resp.json()
    return data


@pytest.mark.asyncio
async def test_full_interview_confirm_flow_activates_profile(client, store) -> None:
    user_id, session_id = uuid4(), uuid4()

    resp = await client.get("/profile/active", headers=_headers(user_id))
    assert resp.status_code == 404

    final = await _run_interview(client, user_id, session_id)
    assert final["state"]["is_complete"] is True
    assert final["state"]["current_step"] == "hitl_confirmation"
    assert final["summary_card"]["requires_user_confirmation"] is True

    # Still inactive until explicit confirmation.
    assert store.profiles == {}

    resp = await client.post(
        "/profile/confirm",
        json={"session_id": str(session_id), "user_overrides": {"excluded_tickers": ["comi"]}},
        headers=_headers(user_id),
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["profile"]["risk_profile"] == "moderate"
    assert body["profile"]["excluded_sectors"] == ["Tobacco"]
    assert body["profile"]["excluded_tickers"] == ["COMI"]
    assert body["profile"]["profile_version"] == 1

    resp = await client.get("/profile/active", headers=_headers(user_id))
    assert resp.status_code == 200
    assert resp.json()["liquidity_floor_pct"] == 70.0

    # The HITL gate is closed: further turns and re-confirmation are rejected.
    resp = await client.post(
        "/interview/message",
        json={"session_id": str(session_id), "message": "طويل الأجل"},
        headers=_headers(user_id),
    )
    assert resp.status_code == 409
    resp = await client.post(
        "/profile/confirm", json={"session_id": str(session_id)}, headers=_headers(user_id)
    )
    assert resp.status_code == 409

    resp = await client.get(f"/interview/sessions/{session_id}", headers=_headers(user_id))
    assert resp.json()["state"]["is_confirmed"] is True


@pytest.mark.asyncio
async def test_confirm_incomplete_interview_is_rejected(client, store) -> None:
    user_id, session_id = uuid4(), uuid4()
    await client.post(
        "/interview/message",
        json={"session_id": str(session_id), "message": INTERVIEW[0]},
        headers=_headers(user_id),
    )
    resp = await client.post(
        "/profile/confirm", json={"session_id": str(session_id)}, headers=_headers(user_id)
    )
    assert resp.status_code == 409
    assert resp.json()["detail"]["code"] == "interview_incomplete"
    assert store.profiles == {}


@pytest.mark.asyncio
async def test_raising_risk_requires_disclaimer(client, store) -> None:
    user_id, session_id = uuid4(), uuid4()
    await _run_interview(client, user_id, session_id)

    payload = {"session_id": str(session_id), "user_overrides": {"risk_profile": "aggressive"}}
    resp = await client.post("/profile/confirm", json=payload, headers=_headers(user_id))
    assert resp.status_code == 422
    assert resp.json()["detail"]["code"] == "risk_disclaimer_required"
    assert store.profiles == {}

    resp = await client.post(
        "/profile/confirm",
        json={**payload, "accept_risk_disclaimer": True},
        headers=_headers(user_id),
    )
    assert resp.status_code == 200
    assert resp.json()["profile"]["risk_profile"] == "aggressive"


@pytest.mark.asyncio
async def test_lowering_risk_needs_no_disclaimer(client) -> None:
    user_id, session_id = uuid4(), uuid4()
    await _run_interview(client, user_id, session_id)
    resp = await client.post(
        "/profile/confirm",
        json={"session_id": str(session_id), "user_overrides": {"risk_profile": "conservative"}},
        headers=_headers(user_id),
    )
    assert resp.status_code == 200
    assert resp.json()["profile"]["risk_profile"] == "conservative"


@pytest.mark.asyncio
async def test_invalid_override_is_rejected(client) -> None:
    user_id, session_id = uuid4(), uuid4()
    await _run_interview(client, user_id, session_id)
    resp = await client.post(
        "/profile/confirm",
        json={"session_id": str(session_id), "user_overrides": {"risk_profile": "yolo"}},
        headers=_headers(user_id),
    )
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_other_users_cannot_access_a_session(client, store) -> None:
    owner, intruder, session_id = uuid4(), uuid4(), uuid4()
    await _run_interview(client, owner, session_id)

    resp = await client.get(f"/interview/sessions/{session_id}", headers=_headers(intruder))
    assert resp.status_code == 404
    resp = await client.post(
        "/interview/message",
        json={"session_id": str(session_id), "message": "طويل الأجل"},
        headers=_headers(intruder),
    )
    assert resp.status_code == 404
    resp = await client.post(
        "/profile/confirm", json={"session_id": str(session_id)}, headers=_headers(intruder)
    )
    assert resp.status_code == 404
    assert store.profiles == {}


@pytest.mark.asyncio
async def test_resume_returns_last_agent_turn(client) -> None:
    user_id, session_id = uuid4(), uuid4()
    first = await client.post(
        "/interview/message",
        json={"session_id": str(session_id), "message": INTERVIEW[0]},
        headers=_headers(user_id),
    )
    resp = await client.get(f"/interview/sessions/{session_id}", headers=_headers(user_id))
    assert resp.status_code == 200
    assert resp.json()["agent_message_ar"] == first.json()["agent_message_ar"]
    assert resp.json()["state"]["current_step"] == "investment_horizon"

    resp = await client.get(f"/interview/sessions/{uuid4()}", headers=_headers(user_id))
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_missing_user_header_is_rejected(client) -> None:
    resp = await client.get("/profile/active")
    assert resp.status_code == 422


@pytest.mark.asyncio
async def test_constraints_patch_requires_active_profile(client) -> None:
    user_id, session_id = uuid4(), uuid4()
    resp = await client.patch(
        "/profile/constraints", json={"excluded_tickers": ["etel"]}, headers=_headers(user_id)
    )
    assert resp.status_code == 404

    await _run_interview(client, user_id, session_id)
    await client.post(
        "/profile/confirm", json={"session_id": str(session_id)}, headers=_headers(user_id)
    )
    resp = await client.patch(
        "/profile/constraints", json={"excluded_tickers": ["etel"]}, headers=_headers(user_id)
    )
    assert resp.status_code == 200
    assert resp.json()["excluded_tickers"] == ["ETEL"]
    assert resp.json()["profile_version"] == 2


@pytest.mark.asyncio
async def test_life_event_is_remembered_only_with_active_profile(client, memory) -> None:
    user_id = uuid4()
    msg = "لقد اشتريت شقة جديدة وأحتاج للسيولة قريباً"

    await client.post(
        "/interview/message",
        json={"session_id": str(uuid4()), "message": msg},
        headers=_headers(user_id),
    )
    assert memory.remembered == []

    session_id = uuid4()
    await _run_interview(client, user_id, session_id)
    await client.post(
        "/profile/confirm", json={"session_id": str(session_id)}, headers=_headers(user_id)
    )
    await client.post(
        "/interview/message",
        json={"session_id": str(uuid4()), "message": msg},
        headers=_headers(user_id),
    )
    assert len(memory.remembered) == 1
    assert memory.remembered[0][1].preference_key == "life_event:housing_purchase"


@pytest.mark.asyncio
async def test_chat_page_is_served(client: httpx.AsyncClient) -> None:
    response = await client.get("http://test/investor/chat")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "/api/v1/investor" in response.text
