"""Step 8 – REST API router tests."""

from __future__ import annotations

from unittest.mock import AsyncMock, patch
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from sqlalchemy import text

from app.db.session import SessionLocal, engine
from app.main import app

BASE = "http://test/api/v1/monitoring"


@pytest_asyncio.fixture(autouse=True, loop_scope="function")
async def dispose_engine_pool():
    """Dispose connections after each test to avoid event-loop conflicts."""
    yield
    await engine.dispose()


# ── Helpers ────────────────────────────────────────────────────────────

USER_A = str(uuid4())
USER_B = str(uuid4())


def _headers(user_id: str = USER_A) -> dict[str, str]:
    return {"X-User-ID": user_id}


def _rsi_rule_payload(ticker: str = "AAPL") -> dict:
    return {
        "name": "RSI Alert",
        "ticker": ticker,
        "parameters": {
            "rule_type": "rsi_threshold",
            "threshold": 70,
            "direction": "above",
        },
        "cooldown_minutes": 60,
    }


# ═══════════════════════════════════════════════════════════════════════
# Rules CRUD
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestRulesRouter:
    async def test_create_rule_201(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            resp = await client.post(
                "/rules", json=_rsi_rule_payload(), headers=_headers()
            )
            assert resp.status_code == 201
            data = resp.json()
            assert data["name"] == "RSI Alert"
            assert data["ticker"] == "AAPL"
            assert data["rule_type"] == "rsi_threshold"
            assert data["is_active"] is True
            rule_id = data["id"]

        # Cleanup
        async with SessionLocal() as session, session.begin():
            await session.execute(
                text("DELETE FROM monitoring_rules WHERE id = :rid"),
                {"rid": rule_id},
            )

    async def test_list_rules(self):
        # Create two rules
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            r1 = await client.post(
                "/rules",
                json=_rsi_rule_payload("AAPL"),
                headers=_headers(),
            )
            r2 = await client.post(
                "/rules",
                json=_rsi_rule_payload("MSFT"),
                headers=_headers(),
            )
            rule_ids = [r1.json()["id"], r2.json()["id"]]

            # List all
            resp = await client.get("/rules", headers=_headers())
            assert resp.status_code == 200
            tickers = {r["ticker"] for r in resp.json()}
            assert "AAPL" in tickers
            assert "MSFT" in tickers

            # Filter by ticker
            resp_filtered = await client.get(
                "/rules", params={"ticker": "AAPL"}, headers=_headers()
            )
            assert resp_filtered.status_code == 200
            assert all(r["ticker"] == "AAPL" for r in resp_filtered.json())

        # Cleanup
        async with SessionLocal() as session, session.begin():
            for rid in rule_ids:
                await session.execute(
                    text("DELETE FROM monitoring_rules WHERE id = :rid"),
                    {"rid": rid},
                )

    async def test_get_rule(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            create_resp = await client.post(
                "/rules", json=_rsi_rule_payload(), headers=_headers()
            )
            rule_id = create_resp.json()["id"]

            resp = await client.get(f"/rules/{rule_id}", headers=_headers())
            assert resp.status_code == 200
            assert resp.json()["id"] == rule_id

        # Cleanup
        async with SessionLocal() as session, session.begin():
            await session.execute(
                text("DELETE FROM monitoring_rules WHERE id = :rid"),
                {"rid": rule_id},
            )

    async def test_update_rule(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            create_resp = await client.post(
                "/rules", json=_rsi_rule_payload(), headers=_headers()
            )
            rule_id = create_resp.json()["id"]

            resp = await client.patch(
                f"/rules/{rule_id}",
                json={"name": "Updated Name"},
                headers=_headers(),
            )
            assert resp.status_code == 200
            assert resp.json()["name"] == "Updated Name"

        # Cleanup
        async with SessionLocal() as session, session.begin():
            await session.execute(
                text("DELETE FROM monitoring_rules WHERE id = :rid"),
                {"rid": rule_id},
            )

    async def test_delete_rule_204(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            create_resp = await client.post(
                "/rules", json=_rsi_rule_payload(), headers=_headers()
            )
            rule_id = create_resp.json()["id"]

            resp = await client.delete(f"/rules/{rule_id}", headers=_headers())
            assert resp.status_code == 204

            # GET should now 404 (soft-deleted = inactive)
            get_resp = await client.get(f"/rules/{rule_id}", headers=_headers())
            assert get_resp.status_code == 404

        # Cleanup
        async with SessionLocal() as session, session.begin():
            await session.execute(
                text("DELETE FROM monitoring_rules WHERE id = :rid"),
                {"rid": rule_id},
            )

    async def test_missing_header_returns_422(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            resp = await client.get("/rules")
            assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════
# Ownership isolation
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestOwnershipIsolation:
    async def test_user_b_cannot_get_user_a_rule(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            # User A creates rule
            create_resp = await client.post(
                "/rules", json=_rsi_rule_payload(), headers=_headers(USER_A)
            )
            rule_id = create_resp.json()["id"]

            # User B tries to GET
            resp = await client.get(f"/rules/{rule_id}", headers=_headers(USER_B))
            assert resp.status_code == 404

        # Cleanup
        async with SessionLocal() as session, session.begin():
            await session.execute(
                text("DELETE FROM monitoring_rules WHERE id = :rid"),
                {"rid": rule_id},
            )

    async def test_user_b_cannot_delete_user_a_rule(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            create_resp = await client.post(
                "/rules", json=_rsi_rule_payload(), headers=_headers(USER_A)
            )
            rule_id = create_resp.json()["id"]

            # User B tries to DELETE
            resp = await client.delete(f"/rules/{rule_id}", headers=_headers(USER_B))
            assert resp.status_code == 404

            # User A can still GET
            get_resp = await client.get(f"/rules/{rule_id}", headers=_headers(USER_A))
            assert get_resp.status_code == 200

        # Cleanup
        async with SessionLocal() as session, session.begin():
            await session.execute(
                text("DELETE FROM monitoring_rules WHERE id = :rid"),
                {"rid": rule_id},
            )


# ═══════════════════════════════════════════════════════════════════════
# Alerts
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestAlertsRouter:
    async def test_list_alerts_empty(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            resp = await client.get("/alerts", headers=_headers())
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)

    async def test_acknowledge_alert(self):
        """Create rule + alert directly in DB, then acknowledge via API."""
        from app.monitoring.models.alert import Alert
        from app.monitoring.models.monitoring_rule import MonitoringRule

        user_id_uuid = __import__("uuid").UUID(USER_A)
        async with SessionLocal() as session, session.begin():
            rule = MonitoringRule(
                user_id=user_id_uuid,
                name="Ack test rule",
                ticker="AAPL",
                rule_type="rsi_threshold",
                parameters={"threshold": 70},
            )
            session.add(rule)
            await session.flush()

            alert = Alert(
                rule_id=rule.id,
                user_id=user_id_uuid,
                ticker="AAPL",
                alert_type="rsi_threshold",
                severity="INFO",
                reason="Test alert for ack",
                evidence={},
            )
            session.add(alert)
            await session.flush()
            alert_id = str(alert.id)
            rule_id = str(rule.id)

        # Acknowledge via API
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            resp = await client.post(
                f"/alerts/{alert_id}/acknowledge",
                headers=_headers(USER_A),
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["id"] == alert_id
            assert data["acknowledged_at"] is not None

            # Second acknowledge should 409
            resp2 = await client.post(
                f"/alerts/{alert_id}/acknowledge",
                headers=_headers(USER_A),
            )
            assert resp2.status_code == 409

        # Cleanup
        async with SessionLocal() as session, session.begin():
            await session.execute(
                text("DELETE FROM alerts WHERE id = :aid"),
                {"aid": alert_id},
            )
            await session.execute(
                text("DELETE FROM monitoring_rules WHERE id = :rid"),
                {"rid": rule_id},
            )

    async def test_acknowledge_nonexistent_404(self):
        fake_id = str(uuid4())
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            resp = await client.post(
                f"/alerts/{fake_id}/acknowledge",
                headers=_headers(),
            )
            assert resp.status_code == 404


# ═══════════════════════════════════════════════════════════════════════
# Admin
# ═══════════════════════════════════════════════════════════════════════


@pytest.mark.asyncio
class TestAdminRouter:
    async def test_trigger_run_202(self):
        with patch(
            "app.monitoring.routers.admin_router.run_monitoring_cycle",
            new_callable=AsyncMock,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url=BASE
            ) as client:
                resp = await client.post("/admin/run")
                assert resp.status_code == 202
                assert "triggered" in resp.json()["detail"].lower()

    async def test_list_runs(self):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url=BASE
        ) as client:
            resp = await client.get("/admin/runs")
            assert resp.status_code == 200
            assert isinstance(resp.json(), list)
