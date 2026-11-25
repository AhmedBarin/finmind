"""Bounded thread memory helpers for Explanation graph checkpoints."""

from __future__ import annotations

from typing import Any


MAX_MEMORY_TURNS = 8
MAX_MEMORY_FIELD_CHARS = 4000


def merge_memory(
    current: list[dict[str, Any]] | None,
    update: list[dict[str, Any]] | None,
) -> list[dict[str, Any]]:
    """Append new turns and retain only the newest bounded window."""
    values = [*(current or []), *(update or [])]
    return values[-MAX_MEMORY_TURNS:]


def memory_entry(*, mode: str, ticker: str | None, question: str, answer: str) -> dict[str, str | None]:
    return {
        "mode": mode[:32],
        "ticker": ticker[:32] if ticker else None,
        "question": question[:MAX_MEMORY_FIELD_CHARS],
        "answer": answer[:MAX_MEMORY_FIELD_CHARS],
    }
