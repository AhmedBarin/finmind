"""FastAPI dependency – extract user identity from request header.

Until a real auth layer is wired up, the user ID is passed as
``X-User-ID`` (a UUID string).
"""

from __future__ import annotations

from uuid import UUID

from fastapi import Header, HTTPException


async def get_current_user_id(
    x_user_id: str = Header(..., alias="X-User-ID"),
) -> UUID:
    """Parse and return the user UUID from the request header."""
    try:
        return UUID(x_user_id)
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail="X-User-ID header must be a valid UUID",
        ) from exc
