"""Rate-limiting boundary.

Routes depend on :func:`rate_limit`, which talks to a :class:`RateLimiter`
protocol. The default backend is an in-process sliding window, which is
enough for a single worker. A shared backend (Redis, Postgres) can replace it
by assigning ``app.state.rate_limiter`` without changing any route.
"""

from __future__ import annotations

import asyncio
import math
import time
from collections import defaultdict, deque
from collections.abc import Awaitable, Callable
from typing import Annotated, Protocol

from fastapi import Depends, HTTPException, Request, status

from app.core.security.config import AuthSettings, get_auth_settings
from app.core.security.dependencies import get_current_principal
from app.core.security.tokens import Principal


class RateLimiter(Protocol):
    async def hit(self, key: str, limit: int, window_seconds: float) -> float | None:
        """Record a hit. Return ``None`` if allowed, else seconds until retry."""


class InMemoryRateLimiter:
    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = asyncio.Lock()

    async def hit(self, key: str, limit: int, window_seconds: float) -> float | None:
        async with self._lock:
            now = self._clock()
            bucket = self._hits[key]
            while bucket and bucket[0] <= now - window_seconds:
                bucket.popleft()
            if len(bucket) >= limit:
                return bucket[0] + window_seconds - now
            bucket.append(now)
            return None


_default_limiter = InMemoryRateLimiter()


def get_rate_limiter(request: Request) -> RateLimiter:
    return getattr(request.app.state, "rate_limiter", _default_limiter)


def rate_limit(
    scope: str, limit: int, window_seconds: float = 60.0
) -> Callable[..., Awaitable[None]]:
    """Build a per-user rate-limit dependency for one route group."""

    async def _dependency(
        principal: Annotated[Principal, Depends(get_current_principal)],
        limiter: Annotated[RateLimiter, Depends(get_rate_limiter)],
        settings: Annotated[AuthSettings, Depends(get_auth_settings)],
    ) -> None:
        if not settings.rate_limit_enabled:
            return
        retry_after = await limiter.hit(
            f"{scope}:{principal.user_id}", limit, window_seconds
        )
        if retry_after is not None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail="Rate limit exceeded",
                headers={"Retry-After": str(max(1, math.ceil(retry_after)))},
            )

    return _dependency
