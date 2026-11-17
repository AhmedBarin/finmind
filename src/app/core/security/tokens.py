"""JWT creation and verification."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from enum import StrEnum
from uuid import UUID

import jwt
from pydantic import BaseModel, ConfigDict

from app.core.security.config import AuthSettings


class Role(StrEnum):
    USER = "user"
    ADMIN = "admin"


class Principal(BaseModel):
    """The authenticated caller, as seen by route code."""

    model_config = ConfigDict(frozen=True)

    user_id: UUID
    role: Role = Role.USER

    @property
    def is_admin(self) -> bool:
        return self.role is Role.ADMIN


class TokenError(Exception):
    """Raised for any invalid token. The message is never shown to clients."""


def create_access_token(
    settings: AuthSettings,
    user_id: UUID,
    role: Role = Role.USER,
    ttl: timedelta | None = None,
    now: datetime | None = None,
) -> str:
    if settings.jwt_secret is None:
        raise TokenError("AUTH_JWT_SECRET is not configured")

    issued = now or datetime.now(tz=UTC)
    expires = issued + (ttl or timedelta(minutes=settings.access_token_ttl_minutes))
    payload = {
        "sub": str(user_id),
        "role": role.value,
        "iss": settings.jwt_issuer,
        "aud": settings.jwt_audience,
        "iat": int(issued.timestamp()),
        "exp": int(expires.timestamp()),
    }
    return jwt.encode(
        payload,
        settings.jwt_secret.get_secret_value(),
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(settings: AuthSettings, token: str) -> Principal:
    if settings.jwt_secret is None:
        raise TokenError("AUTH_JWT_SECRET is not configured")

    try:
        claims = jwt.decode(
            token,
            settings.jwt_secret.get_secret_value(),
            # Pin the algorithm list: never trust the token header's "alg".
            algorithms=[settings.jwt_algorithm],
            issuer=settings.jwt_issuer,
            audience=settings.jwt_audience,
            leeway=settings.leeway_seconds,
            options={"require": ["sub", "exp", "iat", "iss", "aud"]},
        )
    except jwt.PyJWTError as exc:
        raise TokenError(str(exc)) from exc

    try:
        return Principal(
            user_id=UUID(str(claims["sub"])),
            role=Role(claims.get("role", Role.USER.value)),
        )
    except ValueError as exc:
        raise TokenError("invalid subject or role claim") from exc
