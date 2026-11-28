"""Protocols used to decouple Explanation Agent orchestration from providers."""

from __future__ import annotations

from typing import Any, Protocol, TypeVar

from pydantic import BaseModel

from app.explanation.schemas import EvidenceQuery, EvidenceResult

ModelT = TypeVar("ModelT", bound=BaseModel)


class LLMClient(Protocol):
    async def generate_structured(
        self,
        *,
        system_prompt: str,
        user_prompt: str,
        output_model: type[ModelT],
        model_name: str | None = None,
    ) -> ModelT:
        """Generate and validate one structured response."""


class EvidenceRetriever(Protocol):
    async def retrieve(self, query: EvidenceQuery) -> EvidenceResult:
        """Return authorized, source-backed evidence only."""


class ExplanationTool(Protocol):
    name: str

    async def invoke(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute a bounded read-only tool call."""
