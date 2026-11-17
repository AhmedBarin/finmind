"""Shared generate → validate → retry-once loop for every explanation mode."""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import Literal, TypeVar

from pydantic import BaseModel, ValidationError

from app.explanation.grounding import ungrounded_numbers
from app.explanation.language import find_recommendation_language
from app.explanation.llm import ExplanationLLM, ExplanationLLMError

logger = logging.getLogger(__name__)

DraftT = TypeVar("DraftT", bound=BaseModel)
LLMOutcome = Literal["llm", "llm_retry", "fallback"]


def retry_message(issues: list[str]) -> dict[str, str]:
    return {
        "role": "user",
        "content": (
            "Your previous answer was rejected for these reasons:\n- "
            + "\n- ".join(issues)
            + "\nReturn a corrected JSON object that follows every rule."
        ),
    }


def text_issues(text: str, where: str, allowed_numbers: set[float]) -> list[str]:
    """Recommendation language and ungrounded numbers found in ``text``."""
    issues: list[str] = []
    hits = find_recommendation_language(text)
    if hits:
        issues.append(f"{where} contains recommendation language: {', '.join(hits)}")
    bad = ungrounded_numbers(text, allowed_numbers)
    if bad:
        issues.append(f"{where} has numbers not found in the supplied data: {', '.join(bad)}")
    return issues


def dedupe(items: list[str]) -> list[str]:
    return list(dict.fromkeys(item for item in items if item))


async def generate_validated(
    llm: ExplanationLLM,
    messages: list[dict[str, str]],
    draft_model: type[DraftT],
    validate: Callable[[DraftT], list[str]],
    *,
    label: str,
) -> tuple[DraftT | None, LLMOutcome]:
    """Ask for a draft; on schema or validation failure retry once, then give up.

    Returns ``(None, "fallback")`` when the caller must use its safe template.
    """
    for attempt in range(2):
        try:
            raw = await llm.complete(messages)
        except ExplanationLLMError as exc:
            logger.warning("%s generation failed: %s", label, exc)
            return None, "fallback"
        try:
            draft = draft_model.model_validate_json(raw)
        except ValidationError as exc:
            issues = [
                "Output did not match output_schema: "
                + "; ".join(
                    f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}"
                    for e in exc.errors()[:5]
                )
            ]
        else:
            issues = dedupe(validate(draft))
        if not issues:
            return draft, "llm" if attempt == 0 else "llm_retry"
        logger.info("%s draft rejected (attempt %d): %d issue(s)", label, attempt + 1, len(issues))
        messages = [*messages, {"role": "assistant", "content": raw}, retry_message(issues)]
    return None, "fallback"
