"""FastAPI dependency – user identity for monitoring routes.

Delegates to the shared auth layer (``app.core.security``): callers must send
``Authorization: Bearer <jwt>``. The previous ``X-User-ID`` header placeholder
has been removed because it let any caller impersonate any user.
"""

from __future__ import annotations

from app.core.security import get_current_user_id

__all__ = ["get_current_user_id"]
