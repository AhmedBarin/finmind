"""Safe exception handling: unexpected errors never leak internals."""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

logger = logging.getLogger(__name__)


async def _unhandled_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    error_id = uuid.uuid4().hex
    logger.exception(
        "Unhandled error %s on %s %s", error_id, request.method, request.url.path
    )
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error", "error_id": error_id},
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(Exception, _unhandled_exception_handler)
