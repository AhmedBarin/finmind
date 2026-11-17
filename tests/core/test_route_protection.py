"""Every route on the real app must reject unauthenticated callers.

New routers are covered automatically: a route only passes if it is listed in
``PUBLIC_PATHS`` or answers 401 without credentials. No database required —
auth dependencies run before any handler touches a session.
"""

from __future__ import annotations

import re

import httpx
import pytest

from app.main import app

# Paths hidden from the schema (e.g. the dev chat page) are not enumerated.
PUBLIC_PATHS = {"/health"}
_HTTP_METHODS = {"get", "post", "put", "patch", "delete"}

_PATH_PARAM = re.compile(r"\{[^}]+\}")
_DUMMY_UUID = "00000000-0000-4000-8000-000000000000"


def _protected_routes() -> list[tuple[str, str]]:
    routes = []
    for raw_path, operations in app.openapi()["paths"].items():
        if raw_path in PUBLIC_PATHS:
            continue
        path = _PATH_PARAM.sub(_DUMMY_UUID, raw_path)
        for method in sorted(set(operations) & _HTTP_METHODS):
            routes.append((method.upper(), path))
    return routes


PROTECTED = _protected_routes()


def test_app_has_protected_routes():
    prefixes = {path.split("/")[1] for _, path in PROTECTED}
    assert {"news", "api"} <= prefixes


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_route_rejects_missing_credentials(method: str, path: str):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path)
    assert response.status_code == 401, f"{method} {path} -> {response.status_code}"


@pytest.mark.asyncio
@pytest.mark.parametrize(("method", "path"), PROTECTED)
async def test_route_rejects_legacy_user_header(method: str, path: str):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        response = await client.request(method, path, headers={"X-User-ID": _DUMMY_UUID})
    assert response.status_code == 401, f"{method} {path} -> {response.status_code}"
