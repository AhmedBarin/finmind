from datetime import datetime, timezone

import pytest
from pydantic import BaseModel

from app.explanation.generator import StructuredGenerator
from app.explanation.generator import StructuredOutputError
from app.explanation.graph import build_explanation_graph, run_explanation_graph
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


class CountingFailingLLM:
    def __init__(self) -> None:
        self.calls = 0

    async def generate_structured(self, **kwargs):
        self.calls += 1
        raise StructuredOutputError("invalid output")


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
async def test_invalid_input_reaches_fallback_without_calling_llm() -> None:
    llm = CountingFailingLLM()
    graph = build_explanation_graph(
        generator=StructuredGenerator(llm),
        output_model=DemoOutput,
        checkpointer=build_memory(),
    )

    result = await graph.ainvoke(
        {"input_payload": None, "mode": ""},
        config={"configurable": {"thread_id": "invalid-input"}},
    )

    assert result["final_output"]["status"] == "unavailable"
    assert llm.calls == 0


@pytest.mark.asyncio
async def test_same_thread_starts_retry_budget_from_zero_each_run() -> None:
    llm = CountingFailingLLM()
    graph = build_explanation_graph(
        generator=StructuredGenerator(llm),
        output_model=DemoOutput,
        checkpointer=build_memory(),
        max_retries=1,
    )
    config = {"configurable": {"thread_id": "retry-thread"}}
    payload = {"mode": "recommendation", "language": "ar"}

    first = await graph.ainvoke({"input_payload": payload, "mode": "recommendation"}, config=config)
    second = await graph.ainvoke({"input_payload": payload, "mode": "recommendation"}, config=config)

    assert first["final_output"]["status"] == "unavailable"
    assert second["final_output"]["status"] == "unavailable"
    assert llm.calls == 4


@pytest.mark.asyncio
async def test_fake_generator_produces_structured_output() -> None:
    result = await StructuredGenerator(FakeLLM()).generate(
        mode=ExplanationMode.RECOMMENDATION,
        language=ExplanationLanguage.ARABIC,
        context="<untrusted_evidence>{}</untrusted_evidence>",
        output_model=DemoOutput,
    )

    assert result.summary == "grounded"
