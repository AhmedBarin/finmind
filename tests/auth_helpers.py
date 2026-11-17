"""Helpers for authenticating test requests."""

from __future__ import annotations

from uuid import UUID, uuid4

from app.core.security import INTERNAL_TOKEN_HEADER, Role, auth_settings, create_access_token


def bearer_headers(user_id: UUID | None = None, role: Role = Role.USER) -> dict[str, str]:
    token = create_access_token(auth_settings, user_id or uuid4(), role)
    return {"Authorization": f"Bearer {token}"}


def internal_headers() -> dict[str, str]:
    assert auth_settings.internal_service_token is not None
    return {INTERNAL_TOKEN_HEADER: auth_settings.internal_service_token.get_secret_value()}
