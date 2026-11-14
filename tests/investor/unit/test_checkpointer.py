"""Unit tests for LangGraph PostgreSQL and in-memory checkpointer helpers."""

import pytest

from app.investor.checkpointer import (
    create_memory_checkpointer,
    postgres_conninfo_from_database_url,
)


def test_postgres_conninfo_converts_asyncpg_scheme() -> None:
    uri = postgres_conninfo_from_database_url(
        "postgresql+asyncpg://finmind:secret@localhost:5432/finmind_db"
    )
    assert uri == "postgresql://finmind:secret@localhost:5432/finmind_db"


def test_postgres_conninfo_accepts_plain_postgres_scheme() -> None:
    uri = postgres_conninfo_from_database_url(
        "postgresql://finmind:secret@localhost:5432/finmind_db"
    )
    assert uri == "postgresql://finmind:secret@localhost:5432/finmind_db"


def test_postgres_conninfo_rejects_empty_or_non_postgres_urls() -> None:
    with pytest.raises(ValueError, match="empty"):
        postgres_conninfo_from_database_url("   ")

    with pytest.raises(ValueError, match="Unsupported"):
        postgres_conninfo_from_database_url("sqlite+aiosqlite:///./test.db")


def test_create_memory_checkpointer() -> None:
    saver = create_memory_checkpointer()
    assert saver is not None

