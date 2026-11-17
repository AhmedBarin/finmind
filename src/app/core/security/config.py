"""Security settings (PLAN-003).

The identity provider is still **NEEDS CLARIFICATION**, so FinMind verifies
its own signed JWTs. Everything is configurable through ``AUTH_*`` env vars so
an external provider (e.g. RS256 + JWKS) can be swapped in later without
touching route code.

All verification fails closed: if ``AUTH_JWT_SECRET`` or
``AUTH_INTERNAL_SERVICE_TOKEN`` is unset, the corresponding requests are
rejected rather than allowed.
"""

from __future__ import annotations

from pydantic import SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class AuthSettings(BaseSettings):
    jwt_secret: SecretStr | None = None
    jwt_algorithm: str = "HS256"
    jwt_issuer: str = "finmind"
    jwt_audience: str = "finmind-api"
    access_token_ttl_minutes: int = 60
    leeway_seconds: int = 30

    internal_service_token: SecretStr | None = None

    rate_limit_enabled: bool = True

    model_config = SettingsConfigDict(
        env_prefix="AUTH_",
        env_file=".env",
        extra="ignore",
    )


auth_settings = AuthSettings()


def get_auth_settings() -> AuthSettings:
    """FastAPI dependency so tests can override settings."""
    return auth_settings
