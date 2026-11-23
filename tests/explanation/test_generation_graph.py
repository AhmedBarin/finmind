from datetime import datetime, timezone

import pytest
from pydantic import BaseModel

from app.explanation.generator import StructuredGenerator
from app.explanation.graph import build_explanation_graph
from app.explanation.memory import build_memory, thread_config
from app.explanation.prompts import ExplanationPromptBuilder
from app.explanation.schemas import ExplanationLanguage, ExplanationMode


class DemoOutput(BaseModel):
    summary: str
    generated_at: datetime


class FakeLLM:
    async def generate_structured(self, *, system_prompt, user_prompt, output_model, model_name=None):
        assert "never recalculate indicators" in system_prompt.lower()
        assert "<untrusted_evidence>" in user_prompt
        return output_model(summary="grounded", generated_at=datetime.now(timezone.utc))


def test_prompts_support_arabic_and_english() -> None:
    prompts = ExplanationPromptBuilder()

    arabic = prompts.system_prompt(ExplanationMode.RECOMMENDATION, ExplanationLanguage.ARABIC)
    english = prompts.system_prompt(ExplanationMode.STOCK_QA, ExplanationLanguage.ENGLISH)

    assert "Respond in Arabic" in arabic
    assert "Respond in English" in english
    assert "Preserve the exact decision" in arabic


def test_thread_config_rejects_empty_ids() -> None:
    with pytest.raises(ValueError, match="thread_id"):
        thread_config(" ")


def test_graph_compiles_with_bounded_nodes() -> None:
    graph = build_explanation_graph(
        generator=StructuredGenerator(FakeLLM()),
        output_model=DemoOutput,
        checkpointer=build_memory(),
        max_retries=1,
    )

    node_names = set(graph.get_graph().nodes)
    assert {"validate_input", "generate_output", "safe_fallback", "save_output"} <= node_names


@pytest.mark.asyncio
async def test_fake_generator_produces_structured_output() -> None:
    result = await StructuredGenerator(FakeLLM()).generate(
        mode=ExplanationMode.RECOMMENDATION,
        language=ExplanationLanguage.ARABIC,
        context="<untrusted_evidence>{}</untrusted_evidence>",
        output_model=DemoOutput,
    )

    assert result.summary == "grounded"
