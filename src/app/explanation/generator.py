"""Bounded structured output generation for prepared Explanation modes."""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Sequence

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from app.explanation.context_builder import ExplanationContext
from app.explanation.interfaces import LLMClient
from app.explanation.prompts import PROMPT_VERSION, retry_system_prompt, system_prompt
from app.explanation.schemas import (
    ExplanationLanguage,
    ExplanationMode,
)
from app.recommendation.schemas import RecommendationDecision


logger = logging.getLogger(__name__)
MAX_DRAFT_FACTS = 30
MAX_DRAFT_CITATIONS = 30
MAX_DRAFT_LIMITATIONS = 20
MAX_DRAFT_TEXT = 4000


class ExplanationDraft(BaseModel):
    """Untrusted model output before citations and decisions are system-bound."""

    model_config = ConfigDict(extra="forbid")

    summary: str = Field(min_length=1, max_length=1000)
    explanation: str = Field(min_length=1, max_length=MAX_DRAFT_TEXT)
    facts: list[str] = Field(default_factory=list, max_length=MAX_DRAFT_FACTS)
    citation_ids: list[str] = Field(default_factory=list, max_length=MAX_DRAFT_CITATIONS)
    limitations: list[str] = Field(default_factory=list, max_length=MAX_DRAFT_LIMITATIONS)
    disclaimer: str = Field(min_length=1, max_length=1000)
    decision: RecommendationDecision | None = None


class ExplanationGenerator:
    def __init__(self, llm: LLMClient, *, timeout_seconds: float = 20.0) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.llm = llm
        self.timeout_seconds = timeout_seconds

    async def generate(
        self,
        *,
        context: ExplanationContext,
        mode: ExplanationMode,
        language: ExplanationLanguage,
        expected_decision: RecommendationDecision | None,
        validation_errors: Sequence[str] = (),
        retry: bool = False,
    ) -> ExplanationDraft:
        payload = json.dumps(
            {
                "prompt_version": PROMPT_VERSION,
                "request_data": context.user_payload,
                "conversation_memory": context.memory_payload,
                "untrusted_evidence": context.evidence_payload,
                "expected_decision": expected_decision.value if expected_decision else None,
                "validation_errors": list(validation_errors),
                "output_schema": ExplanationDraft.model_json_schema(),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
        mode_prompt = retry_system_prompt(mode, language) if retry else system_prompt(mode, language)
        prompt = f"{context.system_instructions}\n{mode_prompt}"
        logger.info("Generating explanation mode=%s prompt_version=%s retry=%s", mode.value, PROMPT_VERSION, retry)
        try:
            generated = await asyncio.wait_for(
                self.llm.generate_structured(
                    system_prompt=prompt,
                    user_prompt=payload,
                    output_model=ExplanationDraft,
                    model_name=None,
                ),
                timeout=self.timeout_seconds,
            )
        except asyncio.TimeoutError:
            raise
        if isinstance(generated, ExplanationDraft):
            return generated
        if isinstance(generated, BaseModel):
            generated = generated.model_dump(mode="python")
        try:
            return ExplanationDraft.model_validate(generated)
        except ValidationError:
            raise
