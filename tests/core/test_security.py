"""PLAN-003 security boundary tests. No database required."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Annotated
from uuid import UUID, uuid4

import httpx
import jwt
import pytest
from fastapi import Depends, FastAPI
from pydantic import SecretStr

from app.core.security import (
    AuthSettings,
    InMemoryRateLimiter,
    Principal,
    Role,
    TokenError,
    create_access_token,
    decode_access_token,
    get_auth_settings,
    get_current_principal,
    get_current_user_id,
    rate_limit,
    require_admin,
    require_admin_or_internal,
    require_internal_service,
)
from app.core.security.errors import register_exception_handlers

SECRET = "unit-test-secret-0123456789abcdef0123456789"
INTERNAL = "unit-internal-token-0123456789"


def _settings(**overrides) -> AuthSettings:
    values = {
        "jwt_secret": SecretStr(SECRET),
        "internal_service_token": SecretStr(INTERNAL),
    }
    values.update(overrides)
    return AuthSettings(_env_file=None, **values)


def _token(settings: AuthSettings | None = None, **kwargs) -> str:
    return create_access_token(settings or _settings(), kwargs.pop("user_id", uuid4()), **kwargs)


def _bearer(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


# ── Token unit tests ──────────────────────────────────────────────────


class TestTokens:
    def test_round_trip(self):
        uid = uuid4()
        principal = decode_access_token(_settings(), _token(user_id=uid, role=Role.ADMIN))
        assert principal == Principal(user_id=uid, role=Role.ADMIN)
        assert principal.is_admin

    def test_default_role_is_user(self):
        assert decode_access_token(_settings(), _token()).role is Role.USER

    def test_expired_token_rejected(self):
        settings = _settings(leeway_seconds=0)
        old = datetime.now(tz=UTC) - timedelta(hours=2)
        token = create_access_token(settings, uuid4(), ttl=timedelta(minutes=5), now=old)
        with pytest.raises(TokenError):
            decode_access_token(settings, token)

    def test_wrong_secret_rejected(self):
        token = _token(_settings(jwt_secret=SecretStr("another-secret-0123456789abcdef0123")))
        with pytest.raises(TokenError):
            decode_access_token(_settings(), token)

    @pytest.mark.parametrize("field", ["jwt_issuer", "jwt_audience"])
    def test_wrong_issuer_or_audience_rejected(self, field):
        token = _token(_settings(**{field: "someone-else"}))
        with pytest.raises(TokenError):
            decode_access_token(_settings(), token)

    def test_alg_none_rejected(self):
        payload = {
            "sub": str(uuid4()), "role": "admin", "iss": "finmind", "aud": "finmind-api",
            "iat": int(datetime.now(tz=UTC).timestamp()),
            "exp": int((datetime.now(tz=UTC) + timedelta(hours=1)).timestamp()),
        }
        unsigned = jwt.encode(payload, key=None, algorithm="none")
        with pytest.raises(TokenError):
            decode_access_token(_settings(), unsigned)

    def test_missing_exp_rejected(self):
        payload = {"sub": str(uuid4()), "iss": "finmind", "aud": "finmind-api", "iat": 0}
        token = jwt.encode(payload, SECRET, algorithm="HS256")
        with pytest.raises(TokenError):
            decode_access_token(_settings(), token)

    @pytest.mark.parametrize("claims", [{"sub": "not-a-uuid"}, {"role": "superuser"}])
    def test_invalid_subject_or_role_rejected(self, claims):
        now = datetime.now(tz=UTC)
        payload = {
            "sub": str(uuid4()), "iss": "finmind", "aud": "finmind-api",
            "iat": int(now.timestamp()), "exp": int((now + timedelta(hours=1)).timestamp()),
            **claims,
        }
        token = jwt.encode(payload, SECRET, algorithm="HS256")
        with pytest.raises(TokenError):
            decode_access_token(_settings(), token)

    def test_unconfigured_secret_fails_closed(self):
        with pytest.raises(TokenError):
            decode_access_token(_settings(jwt_secret=None), _token())
        with pytest.raises(TokenError):
            create_access_token(_settings(jwt_secret=None), uuid4())


# ── Dependency tests via a throwaway app ──────────────────────────────


def _make_app(settings: AuthSettings) -> FastAPI:
    app = FastAPI()
    register_exception_handlers(app)
    app.dependency_overrides[get_auth_settings] = lambda: settings
    app.state.rate_limiter = InMemoryRateLimiter()

    @app.get("/me")
    async def me(user_id: Annotated[UUID, Depends(get_current_user_id)]):
        return {"user_id": str(user_id)}

    @app.get("/admin", dependencies=[Depends(require_admin)])
    async def admin():
        return {"ok": True}

    @app.get("/internal", dependencies=[Depends(require_internal_service)])
    async def internal():
        return {"ok": True}

    @app.get("/ops", dependencies=[Depends(require_admin_or_internal)])
    async def ops():
        return {"ok": True}

    @app.get("/limited", dependencies=[Depends(rate_limit("test", limit=2))])
    async def limited():
        return {"ok": True}

    @app.get("/boom", dependencies=[Depends(get_current_principal)])
    async def boom():
        raise RuntimeError("secret connection string postgres://user:pw@db")

    return app


async def _get(app: FastAPI, path: str, headers: dict[str, str] | None = None):
    transport = httpx.ASGITransport(app=app, raise_app_exceptions=False)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        return await client.get(path, headers=headers or {})


@pytest.mark.asyncio
class TestDependencies:
    async def test_valid_token_returns_user(self):
        uid = uuid4()
        resp = await _get(_make_app(_settings()), "/me", _bearer(_token(user_id=uid)))
        assert resp.status_code == 200
        assert resp.json() == {"user_id": str(uid)}

    @pytest.mark.parametrize(
        "headers",
        [
            {},
            {"Authorization": "Bearer garbage"},
            {"Authorization": "Basic dXNlcjpwYXNz"},
            {"X-User-ID": str(uuid4())},  # old placeholder must no longer work
        ],
    )
    async def test_missing_or_bad_credentials_401(self, headers):
        resp = await _get(_make_app(_settings()), "/me", headers)
        assert resp.status_code == 401
        assert resp.json() == {"detail": "Not authenticated"}
        assert resp.headers["www-authenticate"] == "Bearer"

    async def test_unconfigured_secret_rejects_everything(self):
        token = _token()
        resp = await _get(_make_app(_settings(jwt_secret=None)), "/me", _bearer(token))
        assert resp.status_code == 401

    async def test_admin_route(self):
        app = _make_app(_settings())
        assert (await _get(app, "/admin", _bearer(_token()))).status_code == 403
        assert (await _get(app, "/admin", _bearer(_token(role=Role.ADMIN)))).status_code == 200
        assert (await _get(app, "/admin")).status_code == 401

    async def test_internal_route(self):
        app = _make_app(_settings())
        assert (await _get(app, "/internal", {"X-Internal-Token": INTERNAL})).status_code == 200
        assert (await _get(app, "/internal", {"X-Internal-Token": "wrong"})).status_code == 401
        assert (await _get(app, "/internal")).status_code == 401
        # A user (even admin) bearer token is not a service credential.
        admin = _bearer(_token(role=Role.ADMIN))
        assert (await _get(app, "/internal", admin)).status_code == 401

    async def test_internal_route_fails_closed_when_unconfigured(self):
        app = _make_app(_settings(internal_service_token=None))
        resp = await _get(app, "/internal", {"X-Internal-Token": ""})
        assert resp.status_code == 401

    async def test_admin_or_internal(self):
        app = _make_app(_settings())
        assert (await _get(app, "/ops", {"X-Internal-Token": INTERNAL})).status_code == 200
        assert (await _get(app, "/ops", _bearer(_token(role=Role.ADMIN)))).status_code == 200
        assert (await _get(app, "/ops", _bearer(_token()))).status_code == 403
        assert (await _get(app, "/ops")).status_code == 401

    async def test_rate_limit_per_user(self):
        app = _make_app(_settings())
        a, b = _bearer(_token()), _bearer(_token())
        assert (await _get(app, "/limited", a)).status_code == 200
        assert (await _get(app, "/limited", a)).status_code == 200
        blocked = await _get(app, "/limited", a)
        assert blocked.status_code == 429
        assert int(blocked.headers["retry-after"]) >= 1
        # Another user has their own budget.
        assert (await _get(app, "/limited", b)).status_code == 200

    async def test_rate_limit_can_be_disabled(self):
        app = _make_app(_settings(rate_limit_enabled=False))
        headers = _bearer(_token())
        for _ in range(5):
            assert (await _get(app, "/limited", headers)).status_code == 200

    async def test_unhandled_error_does_not_leak(self):
        resp = await _get(_make_app(_settings()), "/boom", _bearer(_token()))
        assert resp.status_code == 500
        body = resp.json()
        assert body["detail"] == "Internal server error"
        assert "postgres" not in resp.text
        assert len(body["error_id"]) == 32


@pytest.mark.asyncio
async def test_rate_limiter_window_slides():
    now = [0.0]
    limiter = InMemoryRateLimiter(clock=lambda: now[0])
    assert await limiter.hit("k", 1, 10) is None
    assert await limiter.hit("k", 1, 10) == pytest.approx(10)
    now[0] = 10.0
    assert await limiter.hit("k", 1, 10) is None


# ── Real app: protected routes reject anonymous callers ───────────────


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/news/articles"),
        ("GET", "/api/v1/monitoring/rules"),
        ("POST", "/api/v1/monitoring/rules"),
        ("GET", "/api/v1/monitoring/alerts"),
        ("POST", f"/api/v1/monitoring/alerts/{uuid4()}/acknowledge"),
        ("POST", "/api/v1/monitoring/admin/run"),
        ("GET", "/api/v1/monitoring/admin/runs"),
    ],
)
async def test_real_routes_require_auth(method, path):
    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.request(method, path, json={})
    assert resp.status_code == 401


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["/api/v1/monitoring/admin/run", "/api/v1/monitoring/admin/runs"])
async def test_real_admin_routes_forbid_regular_users(path):
    from app.main import app
    from tests.auth_helpers import bearer_headers

    method = "POST" if path.endswith("/run") else "GET"
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.request(method, path, headers=bearer_headers())
    assert resp.status_code == 403


@pytest.mark.asyncio
async def test_health_stays_public():
    from app.main import app

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        resp = await client.get("/health")
    assert resp.status_code == 200
