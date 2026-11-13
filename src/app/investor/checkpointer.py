"""LangGraph checkpointing factories for PostgreSQL persistence and unit tests."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from urllib.parse import urlsplit, urlunsplit

from langgraph.checkpoint.memory import InMemorySaver
from langgraph.checkpoint.postgres.aio import AsyncPostgresSaver


def postgres_conninfo_from_database_url(database_url: str) -> str:
    """Convert an async SQLAlchemy DATABASE_URL into a psycopg connection URI.

    SQLAlchemy async engines use ``postgresql+asyncpg://...``, while
    ``langgraph-checkpoint-postgres`` connects via ``psycopg`` using
    ``postgresql://...``.
    """
    cleaned = database_url.strip()
    if not cleaned:
        raise ValueError("database_url must not be empty")

    parts = urlsplit(cleaned)
    scheme = parts.scheme
    if scheme == "postgresql+asyncpg":
        scheme = "postgresql"
    elif scheme not in {"postgresql", "postgres"}:
        raise ValueError(
            f"Unsupported database scheme for Postgres checkpointer: {parts.scheme}"
        )

    return urlunsplit((scheme, parts.netloc, parts.path, parts.query, parts.fragment))


def create_memory_checkpointer() -> InMemorySaver:
    """Return an in-memory LangGraph checkpointer for unit tests."""
    return InMemorySaver()


@asynccontextmanager
async def open_postgres_checkpointer(
    database_url: str,
    *,
    setup: bool = False,
) -> AsyncIterator[AsyncPostgresSaver]:
    """Open an async PostgreSQL LangGraph checkpointer context.

    Set ``setup=True`` during controlled app bootstrap to create LangGraph's
    ``checkpoints`` tables if they do not exist yet.
    """
    conninfo = postgres_conninfo_from_database_url(database_url)
    async with AsyncPostgresSaver.from_conn_string(conninfo) as checkpointer:
        if setup:
            await checkpointer.setup()
        yield checkpointer

