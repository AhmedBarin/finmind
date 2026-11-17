"""FastAPI auth dependencies (PLAN-003).

* :func:`get_current_principal` – any valid user bearer token.
* :func:`get_current_user_id` – convenience wrapper returning the UUID.
* :func:`require_admin` – bearer token with ``role=admin``.
* :func:`require_internal_service` – ``X-Internal-Token`` service credential.
* :func:`require_admin_or_internal` – either of the above (admin/ops routes).

Error responses are deliberately generic: callers learn only that they are
unauthenticated (401) or not allowed (403), never why a token failed.
Ownership is enforced by filtering queries on ``user_id``; a record owned by
someone else is reported as 404 so its existence is not leaked.
"""

from __future__ import annotations

import logging
import secrets
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security.config import AuthSettings, get_auth_settings
from app.core.security.tokens import Principal, TokenError, decode_access_token

logger = logging.getLogger(__name__)

_bearer = HTTPBearer(auto_error=False)

INTERNAL_TOKEN_HEADER = "X-Internal-Token"


def _unauthorized() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Not authenticated",
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden() -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Forbidden")


async def get_current_principal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
) -> Principal:
    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized()
    try:
        return decode_access_token(settings, credentials.credentials)
    except TokenError as exc:
        logger.info("Rejected bearer token: %s", exc)
        raise _unauthorized() from None


async def get_current_user_id(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> UUID:
    return principal.user_id


async def require_admin(
    principal: Annotated[Principal, Depends(get_current_principal)],
) -> Principal:
    if not principal.is_admin:
        raise _forbidden()
    return principal


def _internal_token_valid(settings: AuthSettings, token: str | None) -> bool:
    expected = settings.internal_service_token
    if expected is None or not token:
        return False
    return secrets.compare_digest(
        token.encode(), expected.get_secret_value().encode()
    )


async def require_internal_service(
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
    x_internal_token: Annotated[
        str | None, Header(alias=INTERNAL_TOKEN_HEADER)
    ] = None,
) -> None:
    if not _internal_token_valid(settings, x_internal_token):
        raise _unauthorized()


async def require_admin_or_internal(
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)],
    settings: Annotated[AuthSettings, Depends(get_auth_settings)],
    x_internal_token: Annotated[
        str | None, Header(alias=INTERNAL_TOKEN_HEADER)
    ] = None,
) -> None:
    if _internal_token_valid(settings, x_internal_token):
        return
    principal = await get_current_principal(credentials, settings)
    if not principal.is_admin:
        raise _forbidden()
