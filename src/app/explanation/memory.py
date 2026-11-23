"""Short-term thread memory for the Explanation LangGraph."""

from __future__ import annotations

from typing import Any, TypedDict

from langgraph.checkpoint.memory import MemorySaver


class ExplanationState(TypedDict, total=False):
    mode: str
    input_payload: dict[str, Any]
    thread_id: str
    context: str
    evidence: list[dict[str, Any]]
    tool_results: list[dict[str, Any]]
    draft_output: dict[str, Any]
    final_output: dict[str, Any]
    validation_errors: list[str]
    retry_count: int
    status: str
    memory_loaded: bool


def build_memory() -> MemorySaver:
    """Return an in-process checkpointer suitable for the MVP and tests."""
    return MemorySaver()


def thread_config(thread_id: str) -> dict[str, dict[str, str]]:
    if not thread_id or not thread_id.strip():
        raise ValueError("thread_id must not be empty")
    return {"configurable": {"thread_id": thread_id.strip()}}
