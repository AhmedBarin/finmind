"""Bounded LangGraph for prepared recommendation, alert, and follow-up modes."""

from __future__ import annotations

import logging
from datetime import UTC, date, datetime
from typing import Annotated, Any, TypedDict
from uuid import uuid4

from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ValidationError

from app.explanation.adapters import AdaptedInput
from app.explanation.context_builder import ContextBuilder, ExplanationContext
from app.explanation.evidence import NewsEvidenceRetriever, build_evidence_query
from app.explanation.generator import ExplanationDraft, ExplanationGenerator
from app.explanation.memory import MAX_MEMORY_TURNS, memory_entry, merge_memory
from app.explanation.schemas import (
    DataAvailability,
    EvidenceResult,
    ExplanationLanguage,
    ExplanationMode,
    ExplanationResponse,
)
from app.explanation.validator import validate_prepared_explanation_draft
from app.recommendation.schemas import RecommendationDecision


logger = logging.getLogger(__name__)
MAX_GRAPH_STEPS = 12
MAX_EVIDENCE_ITEMS = 30


class ExplanationState(TypedDict, total=False):
    adapted: dict[str, Any]
    evidence: dict[str, Any]
    context: dict[str, str]
    memory: Annotated[list[dict[str, Any]], merge_memory]
    prior_memory: list[dict[str, Any]]
    expected_decision: str | None
    draft: dict[str, Any]
    validation_errors: list[str]
    retry_count: int
    response: dict[str, Any]


def _adapted(state: ExplanationState) -> AdaptedInput:
    value = state["adapted"]
    as_of = value.get("as_of")
    if isinstance(as_of, str):
        as_of = date.fromisoformat(as_of)
    return AdaptedInput(
        mode=ExplanationMode(value["mode"]),
        ticker=value.get("ticker"),
        as_of=as_of,
        payload=value.get("payload", {}),
        status=DataAvailability(value.get("status", DataAvailability.AVAILABLE.value)),
        limitations=tuple(value.get("limitations", [])),
    )


def _evidence(state: ExplanationState) -> EvidenceResult:
    return EvidenceResult.model_validate(state.get("evidence", {"status": "not_found"}))


def _to_json(value: Any) -> Any:
    if isinstance(value, BaseModel):
        return value.model_dump(mode="json")
    if isinstance(value, dict):
        return {str(key): _to_json(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json(item) for item in value]
    return value


def _query_for(adapted: AdaptedInput):
    payload = adapted.payload
    reasons: list[str] = []
    query_text = ""
    alert_type = None
    if adapted.mode is ExplanationMode.RECOMMENDATION:
        recommendation = payload.get("recommendation", {})
        reasons = [
            str(item)
            for item in [
                *recommendation.get("reasons", []),
                *recommendation.get("watch_reasons", []),
            ]
            if item
        ][:20]
        query_text = " ".join(reasons) or f"{adapted.ticker or ''} company news"
    elif adapted.mode is ExplanationMode.ALERT:
        alert = payload.get("alert", {})
        alert_type = str(alert.get("alert_type", "")) or None
        query_text = " ".join(
            item for item in (str(alert.get("reason", "")), alert_type or "") if item
        )
    else:
        query_text = str(payload.get("question", ""))[:1000]
    return build_evidence_query(
        ticker=adapted.ticker,
        as_of=adapted.as_of,
        query_text=query_text[:1000],
        reasons=reasons,
        alert_type=alert_type,
        limit=10,
    )


def _bound_evidence(retrieved: EvidenceResult) -> EvidenceResult:
    return EvidenceResult(
        status=retrieved.status,
        items=retrieved.items[:MAX_EVIDENCE_ITEMS],
        limitations=list(dict.fromkeys(retrieved.limitations))[:20],
        freshness_seconds=retrieved.freshness_seconds,
    )


def _response_status(adapted: AdaptedInput, evidence: EvidenceResult) -> str:
    if adapted.status is DataAvailability.UNAVAILABLE:
        return "unavailable"
    if adapted.status is DataAvailability.NOT_FOUND:
        return "not_found"
    if (
        adapted.status in {DataAvailability.STALE, DataAvailability.PARTIAL}
        or evidence.status
        in {
            DataAvailability.NOT_FOUND,
            DataAvailability.PARTIAL,
            DataAvailability.UNAVAILABLE,
        }
    ):
        return "partial"
    return "ok"


def _fallback_draft(
    adapted: AdaptedInput,
    expected_decision: RecommendationDecision | None,
    *,
    reason: str,
) -> ExplanationDraft:
    language = ExplanationLanguage(
        adapted.payload.get("language", ExplanationLanguage.ARABIC.value)
    )
    if language is ExplanationLanguage.ARABIC:
        summary = (
            f"القرار المسجل: {expected_decision.value}."
            if expected_decision is not None
            else "تعذر إعداد شرح موثوق من السياق المتاح."
        )
        explanation = "تعذر إنشاء شرح موثوق الآن؛ راجع البيانات والقيود المسجلة قبل استخدامها."
        limitation = "تعذر التحقق من الشرح المولّد؛ أُعيدت صياغة آمنة دون إضافة أرقام أو استنتاجات."
        disclaimer = "هذا الشرح لأغراض المعلومات ودعم القرار فقط، وليس نصيحة مالية أو ضماناً للأرباح."
    else:
        summary = (
            f"Recorded decision: {expected_decision.value}."
            if expected_decision is not None
            else "A reliable explanation could not be prepared from the available context."
        )
        explanation = "A reliable explanation could not be generated. Review the recorded data and limitations before using it."
        limitation = "Generated text could not be validated; a safe response was used without adding numbers or conclusions."
        disclaimer = "This explanation is for information and decision support only; it is not financial advice or a guarantee of profit."
    logger.warning("Explanation fallback used mode=%s reason=%s", adapted.mode.value, reason)
    return ExplanationDraft(
        summary=summary,
        explanation=explanation,
        facts=[],
        citation_ids=[],
        limitations=[limitation],
        disclaimer=disclaimer,
        decision=expected_decision,
    )


class ExplanationGraph:
    def __init__(
        self,
        *,
        generator: ExplanationGenerator,
        retriever: NewsEvidenceRetriever,
        checkpointer: Any = None,
    ) -> None:
        self.generator = generator
        self.retriever = retriever
        self.context_builder = ContextBuilder()
        self.graph = self._build(checkpointer)

    def _build(self, checkpointer: Any):
        async def retrieve_evidence(state: ExplanationState) -> dict[str, Any]:
            adapted = _adapted(state)
            try:
                retrieved = await self.retriever.retrieve(_query_for(adapted))
            except Exception:
                retrieved = EvidenceResult(
                    status=DataAvailability.UNAVAILABLE,
                    limitations=["News evidence retrieval is unavailable."],
                )
            return {"evidence": _bound_evidence(retrieved).model_dump(mode="json")}

        async def load_memory(state: ExplanationState) -> dict[str, Any]:
            return {"prior_memory": state.get("memory", [])[-MAX_MEMORY_TURNS:]}

        async def build_context(state: ExplanationState) -> dict[str, Any]:
            adapted = _adapted(state)
            payload = dict(adapted.payload)
            payload["conversation_memory"] = state.get("prior_memory", [])
            adapted = AdaptedInput(
                mode=adapted.mode,
                ticker=adapted.ticker,
                as_of=adapted.as_of,
                payload=payload,
                status=adapted.status,
                limitations=adapted.limitations,
            )
            context = self.context_builder.build(
                adapted,
                _evidence(state),
                memory=state.get("prior_memory", []),
            )
            return {
                "context": {
                    "system_instructions": context.system_instructions,
                    "user_payload": context.user_payload,
                    "evidence_payload": context.evidence_payload,
                    "memory_payload": context.memory_payload,
                }
            }

        async def generate(state: ExplanationState) -> dict[str, Any]:
            adapted = _adapted(state)
            context = ExplanationContext(**state["context"])
            language = ExplanationLanguage(
                adapted.payload.get("language", ExplanationLanguage.ARABIC.value)
            )
            expected_decision = (
                RecommendationDecision(state["expected_decision"])
                if state.get("expected_decision")
                else None
            )
            try:
                draft = await self.generator.generate(
                    context=context,
                    mode=adapted.mode,
                    language=language,
                    expected_decision=expected_decision,
                    validation_errors=state.get("validation_errors", []),
                    retry=bool(state.get("retry_count")),
                )
                return {"draft": draft.model_dump(mode="json"), "validation_errors": []}
            except Exception as exc:
                logger.warning("Explanation generation failed mode=%s error=%s", adapted.mode.value, type(exc).__name__)
                return {"draft": {}, "validation_errors": ["generation_failed"]}

        async def validate(state: ExplanationState) -> dict[str, Any]:
            try:
                draft = ExplanationDraft.model_validate(state.get("draft", {}))
            except ValidationError:
                return {"validation_errors": ["invalid_draft_schema"]}
            adapted = _adapted(state)
            language = ExplanationLanguage(
                adapted.payload.get("language", ExplanationLanguage.ARABIC.value)
            )
            expected = (
                RecommendationDecision(state["expected_decision"])
                if state.get("expected_decision")
                else None
            )
            errors = validate_prepared_explanation_draft(
                draft,
                mode=adapted.mode,
                language=language,
                input_payload=adapted.payload,
                evidence=_evidence(state),
                expected_decision=expected,
            )
            return {"validation_errors": errors}

        async def retry(state: ExplanationState) -> dict[str, Any]:
            return {"retry_count": 1}

        async def fallback(state: ExplanationState) -> dict[str, Any]:
            adapted = _adapted(state)
            expected = (
                RecommendationDecision(state["expected_decision"])
                if state.get("expected_decision")
                else None
            )
            draft = _fallback_draft(
                adapted,
                expected,
                reason=",".join(state.get("validation_errors", [])) or "invalid_output",
            )
            return {"draft": draft.model_dump(mode="json")}

        async def finalize(state: ExplanationState) -> dict[str, Any]:
            adapted = _adapted(state)
            evidence = _evidence(state)
            draft = ExplanationDraft.model_validate(state["draft"])
            expected = (
                RecommendationDecision(state["expected_decision"])
                if state.get("expected_decision")
                else None
            )
            citations = [
                item for item in evidence.items if item.evidence_id in set(draft.citation_ids)
            ]
            limitations = list(adapted.limitations) + list(evidence.limitations) + draft.limitations
            if adapted.status is DataAvailability.STALE:
                limitations.append(
                    "المصدر سجّل البيانات كقديمة؛ تعامل مع الشرح بحذر."
                    if adapted.payload.get("language", "ar") == "ar"
                    else "The source marked its data as stale; treat this explanation with caution."
                )
            limitations = list(dict.fromkeys(limitations))[:20]
            response = ExplanationResponse(
                status=_response_status(adapted, evidence),
                explanation_type=adapted.mode.value,
                ticker=adapted.ticker,
                decision=expected,
                summary=draft.summary,
                explanation=draft.explanation,
                facts=draft.facts,
                citations=citations,
                limitations=limitations,
                disclaimer=(
                    "هذا الشرح لأغراض المعلومات ودعم القرار فقط، وليس نصيحة مالية أو ضماناً للأرباح."
                    if adapted.payload.get("language", "ar") == "ar"
                    else "This explanation is for information and decision support only; it is not financial advice or a guarantee of profit."
                ),
                generated_at=datetime.now(UTC),
            )
            return {"response": response.model_dump(mode="json")}

        async def save_memory(state: ExplanationState) -> dict[str, Any]:
            adapted = _adapted(state)
            response = ExplanationResponse.model_validate(state["response"])
            question = str(
                adapted.payload.get("question")
                or adapted.payload.get("recommendation", {}).get("ticker", "")
                or adapted.payload.get("alert", {}).get("reason", "")
            )
            return {
                "memory": [
                    memory_entry(
                        mode=adapted.mode.value,
                        ticker=adapted.ticker,
                        question=question,
                        answer=f"{response.summary}\n{response.explanation}",
                    )
                ]
            }

        def after_validation(state: ExplanationState) -> str:
            return "finalize" if not state.get("validation_errors") else "retry"

        def after_retry(state: ExplanationState) -> str:
            return "fallback" if state.get("validation_errors") else "finalize"

        workflow = StateGraph(ExplanationState)
        workflow.add_node("retrieve_evidence", retrieve_evidence)
        workflow.add_node("load_memory", load_memory)
        workflow.add_node("build_context", build_context)
        workflow.add_node("generate", generate)
        workflow.add_node("validate", validate)
        workflow.add_node("retry", retry)
        workflow.add_node("fallback", fallback)
        workflow.add_node("finalize", finalize)
        workflow.add_node("save_memory", save_memory)
        workflow.add_edge(START, "retrieve_evidence")
        workflow.add_edge("retrieve_evidence", "load_memory")
        workflow.add_edge("load_memory", "build_context")
        workflow.add_edge("build_context", "generate")
        workflow.add_conditional_edges(
            "generate",
            lambda state: "validate_retry" if state.get("retry_count") else "validate",
            {"validate": "validate", "validate_retry": "validate_retry"},
        )
        workflow.add_conditional_edges(
            "validate", after_validation, {"finalize": "finalize", "retry": "retry"}
        )
        workflow.add_edge("retry", "generate")
        # Route the retry pass through its own validator before choosing fallback.
        workflow.add_node("validate_retry", validate)
        workflow.add_conditional_edges(
            "validate_retry", after_retry, {"finalize": "finalize", "fallback": "fallback"}
        )
        workflow.add_edge("fallback", "finalize")
        workflow.add_edge("finalize", "save_memory")
        workflow.add_edge("save_memory", END)
        return workflow.compile(checkpointer=checkpointer)

    async def ainvoke(
        self,
        *,
        adapted: AdaptedInput,
        user_id: str,
        thread_id: str | None,
        expected_decision: RecommendationDecision | None = None,
    ) -> ExplanationResponse:
        thread_key = f"explanation:{user_id}:{thread_id or uuid4()}"
        result = await self.graph.ainvoke(
            {
                "adapted": {
                    "mode": adapted.mode.value,
                    "ticker": adapted.ticker,
                    "as_of": adapted.as_of.isoformat() if adapted.as_of else None,
                    "payload": _to_json(adapted.payload),
                    "status": adapted.status.value,
                    "limitations": list(adapted.limitations),
                },
                "expected_decision": expected_decision.value if expected_decision else None,
                "retry_count": 0,
            },
            config={
                "configurable": {
                    "thread_id": thread_key,
                    "checkpoint_ns": "explanation-v1",
                },
                "recursion_limit": MAX_GRAPH_STEPS,
            },
        )
        return ExplanationResponse.model_validate(result["response"])
