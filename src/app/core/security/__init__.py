"""Shared authentication, authorization and rate limiting (PLAN-003)."""

from app.core.security.config import AuthSettings, auth_settings, get_auth_settings
from app.core.security.dependencies import (
    INTERNAL_TOKEN_HEADER,
    get_current_principal,
    get_current_user_id,
    require_admin,
    require_admin_or_internal,
    require_internal_service,
)
from app.core.security.rate_limit import InMemoryRateLimiter, RateLimiter, rate_limit
from app.core.security.tokens import (
    Principal,
    Role,
    TokenError,
    create_access_token,
    decode_access_token,
)

__all__ = [
    "INTERNAL_TOKEN_HEADER",
    "AuthSettings",
    "InMemoryRateLimiter",
    "Principal",
    "RateLimiter",
    "Role",
    "TokenError",
    "auth_settings",
    "create_access_token",
    "decode_access_token",
    "get_auth_settings",
    "get_current_principal",
    "get_current_user_id",
    "require_admin",
    "require_admin_or_internal",
    "require_internal_service",
    "rate_limit",
]
