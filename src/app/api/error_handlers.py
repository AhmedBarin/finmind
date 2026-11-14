"""Safe API error handlers that do not expose internals or secrets."""

from fastapi import Request
from fastapi.responses import JSONResponse


async def safe_unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", "unknown")
    return JSONResponse(status_code=500, content={"detail": "Internal server error", "trace_id": trace_id})
