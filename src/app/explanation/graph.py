"""Bounded LangGraph orchestration shared by Explanation modes."""

from __future__ import annotations

import json
from typing import Any

from langgraph.graph import END, START, StateGraph

from app.explanation.generator import StructuredGenerationError, StructuredGenerator
from app.explanation.memory import ExplanationState, build_memory, thread_config
from app.explanation.schemas import ExplanationLanguage, ExplanationMode


def build_explanation_graph(
    *,
    generator: StructuredGenerator,
    output_model: type,
    checkpointer=None,
    max_retries: int = 1,
):
    """Compile a graph with bounded generation and retry transitions."""

    if max_retries < 0 or max_retries > 2:
        raise ValueError("max_retries must be between 0 and 2")
    checkpointer = checkpointer or build_memory()
    graph = StateGraph(ExplanationState)

    def validate_input(state: ExplanationState) -> dict[str, Any]:
        payload = state.get("input_payload")
        mode = state.get("mode") or (payload or {}).get("mode")
        errors: list[str] = []
        if not isinstance(payload, dict):
            errors.append("input_payload must be an object")
        if mode not in {item.value for item in ExplanationMode}:
            errors.append("mode is unsupported")
        return {"validation_errors": errors, "mode": mode or ""}

    def detect_mode(state: ExplanationState) -> dict[str, Any]:
        return {"mode": state["mode"]}

    def load_memory(state: ExplanationState) -> dict[str, Any]:
        return {"memory_loaded": True}

    def build_context(state: ExplanationState) -> dict[str, Any]:
        payload = state.get("input_payload", {})
        return {
            "context": payload.get("context")
            or json.dumps(payload, ensure_ascii=False, sort_keys=True)
        }

    async def generate_output(state: ExplanationState) -> dict[str, Any]:
        errors = state.get("validation_errors", [])
        if errors and state.get("retry_count", 0) == 0:
            return {"final_output": {"status": "unavailable", "errors": errors}}
        payload = state.get("input_payload", {})
        language = ExplanationLanguage(payload.get("language", "ar"))
        try:
            result = await generator.generate(
                mode=ExplanationMode(state["mode"]),
                language=language,
                context=state.get("context", ""),
                output_model=output_model,
            )
        except (StructuredGenerationError, ValueError) as exc:
            return {
                "draft_output": {},
                "validation_errors": [str(exc)],
                "retry_count": state.get("retry_count", 0) + 1,
            }
        return {
            "draft_output": result.model_dump(mode="json"),
            "validation_errors": [],
        }

    def validate_output(state: ExplanationState) -> str:
        if state.get("validation_errors"):
            if state.get("retry_count", 0) <= max_retries:
                return "retry"
            return "fallback"
        if not state.get("draft_output"):
            return "fallback"
        return "save"

    def retry_output(state: ExplanationState) -> dict[str, Any]:
        return {"retry_count": state.get("retry_count", 0) + 1, "validation_errors": []}

    def safe_fallback(state: ExplanationState) -> dict[str, Any]:
        return {
            "final_output": {
                "status": "unavailable",
                "limitations": ["A validated explanation could not be generated."],
            }
        }

    def save_output(state: ExplanationState) -> dict[str, Any]:
        return {"final_output": state.get("draft_output", {}), "status": "ok"}

    graph.add_node("validate_input", validate_input)
    graph.add_node("detect_mode", detect_mode)
    graph.add_node("load_memory", load_memory)
    graph.add_node("build_context", build_context)
    graph.add_node("generate_output", generate_output)
    graph.add_node("retry_output", retry_output)
    graph.add_node("safe_fallback", safe_fallback)
    graph.add_node("save_output", save_output)
    graph.add_edge(START, "validate_input")
    graph.add_edge("validate_input", "detect_mode")
    graph.add_edge("detect_mode", "load_memory")
    graph.add_edge("load_memory", "build_context")
    graph.add_edge("build_context", "generate_output")
    graph.add_conditional_edges(
        "generate_output",
        validate_output,
        {"retry": "retry_output", "fallback": "safe_fallback", "save": "save_output"},
    )
    graph.add_edge("retry_output", "generate_output")
    graph.add_edge("safe_fallback", END)
    graph.add_edge("save_output", END)
    return graph.compile(checkpointer=checkpointer)


async def run_explanation_graph(graph, *, payload: dict[str, Any], thread_id: str) -> dict[str, Any]:
    """Run a compiled graph with a bounded recursion limit."""
    result = await graph.ainvoke(
        {"input_payload": payload, "mode": payload.get("mode", "")},
        config={**thread_config(thread_id), "recursion_limit": 20},
    )
    return result
