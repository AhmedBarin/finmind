"""Request-level protections shared by API routes."""

from collections import defaultdict, deque
from time import monotonic
from uuid import uuid4

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-ID") or str(uuid4())
        request.state.trace_id = trace_id
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        return response


class NewsAgentRateLimiter:
    def __init__(self, *, limit: int = 30, window_seconds: int = 60) -> None:
        self.limit = limit
        self.window_seconds = window_seconds
        self._requests: dict[str, deque[float]] = defaultdict(deque)

    def check(self, client_key: str) -> None:
        now = monotonic()
        timestamps = self._requests[client_key]
        while timestamps and now - timestamps[0] >= self.window_seconds:
            timestamps.popleft()
        if len(timestamps) >= self.limit:
            raise HTTPException(status_code=429, detail="News Agent rate limit exceeded")
        timestamps.append(now)


def check_news_agent_rate_limit(request: Request) -> None:
    limiter = getattr(request.app.state, "news_agent_rate_limiter", None)
    if limiter is None:
        limiter = NewsAgentRateLimiter()
        request.app.state.news_agent_rate_limiter = limiter
    client_key = request.client.host if request.client else "unknown"
    limiter.check(client_key)


def validate_agent_message(message: str) -> str:
    value = message.strip()
    if not value:
        raise HTTPException(status_code=400, detail="Message must not be blank")
    if len(value) > 4000:
        raise HTTPException(status_code=400, detail="Message exceeds the maximum length")
    return value
