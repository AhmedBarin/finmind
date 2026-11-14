"""Local dev server: ``uv run python -m app.dev_server``.

On Windows, uvicorn runs on the ProactorEventLoop, which psycopg (used by the
LangGraph Postgres checkpointer) cannot use in async mode. This launcher runs
uvicorn on a SelectorEventLoop so the app starts on every platform.
"""

from __future__ import annotations

import asyncio
import os
import sys

import uvicorn


def main() -> None:
    config = uvicorn.Config(
        "app.main:app",
        host=os.environ.get("HOST", "127.0.0.1"),
        port=int(os.environ.get("PORT", "8000")),
    )
    server = uvicorn.Server(config)
    loop_factory = asyncio.SelectorEventLoop if sys.platform == "win32" else None
    asyncio.run(server.serve(), loop_factory=loop_factory)


if __name__ == "__main__":
    main()
