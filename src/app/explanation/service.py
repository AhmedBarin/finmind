"""Prepared-input Explanation Agent service for modes 1–3."""

from __future__ import annotations

from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.explanation.adapters import (
    AdaptedInput,
    adapt_alert,
    adapt_follow_up,
    adapt_recommendation,
)
from app.explanation.context_builder import ContextBuilder
from app.explanation.evidence import NewsEvidenceRetriever, build_evidence_query
from app.explanation.graph import build_explanation_graph, run_explanation_graph
from app.explanation.interfaces import EvidenceRetriever
from app.explanation.memory import build_memory
from app.explanation.schemas import (
    AlertExplanationRequest,
    DataAvailability,
    EvidenceResult,
    ExplanationLanguage,
    ExplanationResponse,
    FollowUpRequest,
    RecommendationExplanationRequest,
)
from app.explanation.constants import (
    ARABIC_RISK_DISCLAIMER,
    ENGLISH_RISK_DISCLAIMER,
)
from app.explanation.generator import StructuredGenerator


class PreparedExplanationService:
    """Coordinate adapters, evidence, graph execution, and typed responses."""

    def __init__(
        self,
        *,
        generator: StructuredGenerator,
        evidence_retriever: EvidenceRetriever | None = None,
        checkpointer=None,
    ) -> None:
        self.generator = generator
        self.evidence_retriever = (
            NewsEvidenceRetriever(evidence_retriever)
            if evidence_retriever is not None
            else None
        )
        self.context_builder = ContextBuilder()
        self.graph = build_explanation_graph(
            generator=generator,
            output_model=ExplanationResponse,
            checkpointer=checkpointer or build_memory(),
            max_retries=1,
        )

    async def explain_recommendation(
        self, request: RecommendationExplanationRequest
    ) -> ExplanationResponse:
        adapted = adapt_recommendation(request)
        evidence = await self._recommendation_evidence(request, adapted)
        return await self._run(adapted, evidence, request.thread_id)

    async def explain_alert(self, request: AlertExplanationRequest) -> ExplanationResponse:
        adapted = adapt_alert(request)
        evidence = await self._alert_evidence(request, adapted)
        return await self._run(adapted, evidence, request.thread_id)

    async def explain_follow_up(self, request: FollowUpRequest) -> ExplanationResponse:
        adapted = adapt_follow_up(request)
        evidence = EvidenceResult(
            status=DataAvailability.NOT_FOUND,
            limitations=["No additional evidence was requested for this follow-up."],
        )
        return await self._run(adapted, evidence, request.thread_id)

    async def _recommendation_evidence(
        self,
        request: RecommendationExplanationRequest,
        adapted: AdaptedInput,
    ) -> EvidenceResult:
        if request.news_evidence:
            return EvidenceResult(
                status=DataAvailability.AVAILABLE,
                items=request.news_evidence,
            )
        if self.evidence_retriever is None:
            return EvidenceResult(
                status=DataAvailability.NOT_FOUND,
                limitations=["No news evidence was supplied."],
            )
        reasons = request.recommendation.reasons + request.recommendation.watch_reasons
        return await self.evidence_retriever.retrieve(
            build_evidence_query(
                ticker=adapted.ticker,
                as_of=adapted.as_of,
                reasons=reasons,
            )
        )

    async def _alert_evidence(
        self,
        request: AlertExplanationRequest,
        adapted: AdaptedInput,
    ) -> EvidenceResult:
        if request.news_evidence:
            return EvidenceResult(
                status=DataAvailability.AVAILABLE,
                items=request.news_evidence,
            )
        if self.evidence_retriever is None:
            return EvidenceResult(
                status=DataAvailability.NOT_FOUND,
                limitations=["No news evidence was supplied."],
            )
        return await self.evidence_retriever.retrieve(
            build_evidence_query(
                ticker=adapted.ticker,
                as_of=adapted.as_of,
                alert_type=request.alert.alert_type,
            )
        )

    async def _run(
        self,
        adapted: AdaptedInput,
        evidence: EvidenceResult,
        thread_id: str | None,
    ) -> ExplanationResponse:
        context = self.context_builder.build(adapted, evidence)
        payload = {
            **adapted.payload,
            "mode": adapted.mode.value,
            "context": context.rendered,
            "evidence_status": evidence.status.value,
        }
        effective_thread_id = thread_id or str(uuid4())
        try:
            result = await run_explanation_graph(
                self.graph,
                payload=payload,
                thread_id=effective_thread_id,
            )
        except Exception:
            return self._fallback(adapted, status="unavailable")

        final_output = result.get("final_output")
        if not isinstance(final_output, dict):
            return self._fallback(adapted, status="unavailable")
        try:
            response = ExplanationResponse.model_validate(final_output)
        except Exception:
            return self._fallback(adapted, status="unavailable")
        if response.explanation_type != adapted.mode.value:
            return self._fallback(adapted, status="unavailable")
        if adapted.mode.value == "recommendation":
            expected = adapted.payload["recommendation"]["decision"]
            if response.decision is None or response.decision.value != expected:
                return self._fallback(adapted, status="partial")
        if adapted.status is not DataAvailability.AVAILABLE and response.status == "ok":
            response = response.model_copy(update={"status": "partial"})
        return response

    def _fallback(self, adapted: AdaptedInput, *, status: str) -> ExplanationResponse:
        language = adapted.payload.get("language", ExplanationLanguage.ARABIC.value)
        disclaimer = (
            ARABIC_RISK_DISCLAIMER
            if language == ExplanationLanguage.ARABIC.value
            else ENGLISH_RISK_DISCLAIMER
        )
        summary = (
            "تعذر إنشاء شرح موثق من البيانات المتاحة."
            if language == ExplanationLanguage.ARABIC.value
            else "A grounded explanation could not be generated from the available data."
        )
        return ExplanationResponse(
            status=status,
            explanation_type=adapted.mode.value,
            ticker=adapted.ticker,
            decision=(
                adapted.payload["recommendation"]["decision"]
                if adapted.mode.value == "recommendation"
                else None
            ),
            summary=summary,
            explanation=summary,
            limitations=list(adapted.limitations)
            + ["The response was produced by the safe fallback."],
            disclaimer=disclaimer,
            trace_id=uuid4(),
            generated_at=datetime.now(timezone.utc),
        )
