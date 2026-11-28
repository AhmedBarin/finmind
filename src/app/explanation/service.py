"""Service orchestrator for the 4 Explanation Agent modes (PLAN-013).

Modes:
- ``recommendation``: US-008 — Explain an upstream recommendation decision.
- ``alert``:          US-009 — Explain a monitoring alert.
- ``follow_up``:      US-010 — Handle follow-up questions preserving context.
- ``stock_qa``:       US-011 — Answer stock Q&A using the 5 read-only tools.

Invariants:
- The underlying recommendation or alert decision is **never** modified.
- The standard Arabic financial disclaimer is appended to **all** responses.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import Any
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

from app.explanation.adapters import (
    AdaptedInput,
    adapt_alert,
    adapt_follow_up,
    adapt_recommendation,
)
from app.explanation.constants import ARABIC_RISK_DISCLAIMER, ENGLISH_RISK_DISCLAIMER
from app.explanation.context_builder import ContextBuilder
from app.explanation.evidence import NewsEvidenceRetriever, build_evidence_query
from app.explanation.interfaces import ExplanationTool, LLMClient
from app.explanation.safety import (
    annotate_data_issues,
    contains_recommendation_language,
    get_correction_prompt,
    get_safe_fallback,
    split_intent,
    validate_grounding,
)
from app.explanation.schemas import (
    AlertExplanationRequest,
    DataAvailability,
    EvidenceResult,
    ExplanationResponse,
    FollowUpRequest,
    RecommendationExplanationRequest,
    StockQAFact,
    StockQARequest,
    StockQAResponse,
)

logger = logging.getLogger(__name__)


def _disclaimer(language: str) -> str:
    return ARABIC_RISK_DISCLAIMER if language == "ar" else ENGLISH_RISK_DISCLAIMER


def _now() -> datetime:
    return datetime.now(tz=UTC)


# ═══════════════════════════════════════════════════════════════════════════
# LLM response schema (internal)
# ═══════════════════════════════════════════════════════════════════════════


class _LLMExplanation(BaseModel):
    """Structured output the LLM must produce."""

    summary: str = Field(min_length=1)
    explanation: str = Field(min_length=1)
    facts: list[str] = Field(default_factory=list)


class _LLMQAAnswer(BaseModel):
    """Structured output for stock Q&A."""

    answer: str = Field(min_length=1)
    facts: list[dict[str, str]] = Field(default_factory=list)


# ═══════════════════════════════════════════════════════════════════════════
# Explanation Service
# ═══════════════════════════════════════════════════════════════════════════


class ExplanationService:
    """Orchestrates all 4 explanation modes."""

    def __init__(
        self,
        llm: LLMClient,
        evidence_retriever: NewsEvidenceRetriever | None = None,
        tools: list[ExplanationTool] | None = None,
    ) -> None:
        self._llm = llm
        self._evidence = evidence_retriever
        self._tools = {t.name: t for t in (tools or [])}
        self._context_builder = ContextBuilder()

    # ── Mode: Recommendation (US-008) ────────────────────────────────

    async def explain_recommendation(
        self,
        request: RecommendationExplanationRequest,
        trace_id: UUID | None = None,
    ) -> ExplanationResponse:
        language = request.language.value
        adapted = adapt_recommendation(request)
        evidence = await self._fetch_evidence(adapted)
        ctx = self._context_builder.build(adapted, evidence)

        llm_result = await self._generate_explanation(ctx, language)

        return ExplanationResponse(
            status=self._map_status(adapted.status),
            explanation_type="recommendation",
            ticker=adapted.ticker,
            decision=request.recommendation.decision,
            summary=llm_result.summary,
            explanation=llm_result.explanation,
            facts=llm_result.facts,
            citations=evidence.items if evidence else [],
            limitations=list(adapted.limitations)
            + (evidence.limitations if evidence else []),
            disclaimer=_disclaimer(language),
            trace_id=trace_id or uuid4(),
            generated_at=_now(),
        )

    # ── Mode: Alert (US-009) ─────────────────────────────────────────

    async def explain_alert(
        self,
        request: AlertExplanationRequest,
        trace_id: UUID | None = None,
    ) -> ExplanationResponse:
        language = request.language.value
        adapted = adapt_alert(request)
        evidence = await self._fetch_evidence(adapted)
        ctx = self._context_builder.build(adapted, evidence)

        llm_result = await self._generate_explanation(ctx, language)

        return ExplanationResponse(
            status=self._map_status(adapted.status),
            explanation_type="alert",
            ticker=adapted.ticker,
            decision=None,
            summary=llm_result.summary,
            explanation=llm_result.explanation,
            facts=llm_result.facts,
            citations=evidence.items if evidence else [],
            limitations=list(adapted.limitations)
            + (evidence.limitations if evidence else []),
            disclaimer=_disclaimer(language),
            trace_id=trace_id or uuid4(),
            generated_at=_now(),
        )

    # ── Mode: Follow-Up (US-010) ─────────────────────────────────────

    async def handle_follow_up(
        self,
        request: FollowUpRequest,
        trace_id: UUID | None = None,
    ) -> ExplanationResponse:
        language = request.language.value
        adapted = adapt_follow_up(request)
        evidence = await self._fetch_evidence(adapted)
        ctx = self._context_builder.build(adapted, evidence)

        llm_result = await self._generate_explanation(ctx, language)

        return ExplanationResponse(
            status=self._map_status(adapted.status),
            explanation_type="follow_up",
            ticker=adapted.ticker,
            decision=None,
            summary=llm_result.summary,
            explanation=llm_result.explanation,
            facts=llm_result.facts,
            citations=evidence.items if evidence else [],
            limitations=list(adapted.limitations)
            + (evidence.limitations if evidence else []),
            disclaimer=_disclaimer(language),
            trace_id=trace_id or uuid4(),
            generated_at=_now(),
        )

    # ── Mode: Stock Q&A (US-011) ─────────────────────────────────────

    async def answer_stock_qa(
        self,
        request: StockQARequest,
        trace_id: UUID | None = None,
    ) -> StockQAResponse:
        language = request.language.value
        tickers = request.tickers

        # Intent splitting: check for advisory intent
        descriptive, advisory = split_intent(request.question)
        if advisory and not descriptive:
            # Purely advisory → return safe fallback
            return StockQAResponse(
                status="ok",
                tickers=tickers,
                data_date=None,
                freshness_seconds=None,
                answer=get_safe_fallback(language),
                facts=[],
                limitations=["Advisory questions are not supported."],
                disclaimer=_disclaimer(language),
                trace_id=trace_id or uuid4(),
                generated_at=_now(),
            )

        # Execute tools for data gathering
        tool_outputs = await self._execute_tools(tickers, request.max_tool_calls)

        # Annotate data issues
        data_issues = annotate_data_issues(tool_outputs, language)

        # Build LLM prompt from tool outputs
        answer_text, facts = await self._generate_qa_answer(
            request.question,
            tickers,
            tool_outputs,
            language,
        )

        # Safety check: reject recommendation language
        if contains_recommendation_language(answer_text):
            # Retry once with correction prompt
            answer_text, facts = await self._generate_qa_answer(
                request.question,
                tickers,
                tool_outputs,
                language,
                correction=get_correction_prompt(language),
            )
            if contains_recommendation_language(answer_text):
                answer_text = get_safe_fallback(language)
                facts = []

        # Grounding validation
        is_grounded, ungrounded = validate_grounding(answer_text, tool_outputs)
        limitations = data_issues.copy()
        if not is_grounded:
            if language == "ar":
                limitations.append(
                    f"بعض الأرقام الواردة ({', '.join(ungrounded[:3])}) لم يتم التحقق من مصدرها."
                )
            else:
                limitations.append(
                    f"Some numbers ({', '.join(ungrounded[:3])}) could not be verified against source data."
                )

        # Determine data_date from tool outputs
        data_date = self._extract_latest_data_date(tool_outputs)
        freshness = self._extract_min_freshness(tool_outputs)

        return StockQAResponse(
            status="ok" if not data_issues else "partial",
            tickers=tickers,
            data_date=data_date,
            freshness_seconds=freshness,
            answer=answer_text,
            facts=facts,
            limitations=limitations,
            disclaimer=_disclaimer(language),
            trace_id=trace_id or uuid4(),
            generated_at=_now(),
        )

    # ═══════════════════════════════════════════════════════════════════
    # Private helpers
    # ═══════════════════════════════════════════════════════════════════

    async def _fetch_evidence(self, adapted: AdaptedInput) -> EvidenceResult | None:
        if self._evidence is None:
            return None
        query = build_evidence_query(
            ticker=adapted.ticker,
            as_of=adapted.as_of,
            reasons=adapted.payload.get("recommendation", {}).get("reasons", [])
            if isinstance(adapted.payload.get("recommendation"), dict)
            else [],
        )
        return await self._evidence.retrieve(query)

    async def _generate_explanation(
        self,
        ctx: Any,
        language: str,
    ) -> _LLMExplanation:
        """Generate a structured explanation via the LLM."""
        lang_instruction = (
            "أجب باللغة العربية فقط." if language == "ar" else "Answer in English only."
        )
        system = f"{ctx.system_instructions}\n{lang_instruction}"
        try:
            return await self._llm.generate_structured(
                system_prompt=system,
                user_prompt=ctx.rendered,
                output_model=_LLMExplanation,
            )
        except Exception:
            logger.exception("LLM generation failed")
            fallback_text = (
                "تعذر إنشاء الشرح حالياً. يرجى المحاولة لاحقاً."
                if language == "ar"
                else "Could not generate explanation at this time. Please try again later."
            )
            return _LLMExplanation(
                summary=fallback_text,
                explanation=fallback_text,
                facts=[],
            )

    async def _execute_tools(
        self,
        tickers: list[str],
        max_calls: int,
    ) -> list[dict[str, Any]]:
        """Execute tools for each ticker up to max_calls."""
        outputs: list[dict[str, Any]] = []
        calls = 0

        for ticker in tickers:
            if calls >= max_calls:
                break
            # Always try technical_snapshot first
            if "technical_snapshot" in self._tools and calls < max_calls:
                result = await self._tools["technical_snapshot"].invoke(
                    {"ticker": ticker}
                )
                outputs.append(result)
                calls += 1

            # Then price_history for context
            if "price_history" in self._tools and calls < max_calls:
                result = await self._tools["price_history"].invoke(
                    {"ticker": ticker, "days": 30}
                )
                outputs.append(result)
                calls += 1

        # Glossary is free (no DB)
        if "indicator_glossary" in self._tools and calls < max_calls:
            result = await self._tools["indicator_glossary"].invoke({})
            outputs.append(result)

        return outputs

    async def _generate_qa_answer(
        self,
        question: str,
        tickers: list[str],
        tool_outputs: list[dict[str, Any]],
        language: str,
        correction: str | None = None,
    ) -> tuple[str, list[StockQAFact]]:
        """Generate Q&A answer from tool outputs via LLM."""
        import json

        lang_instruction = (
            "أجب باللغة العربية فقط. اشرح البيانات الفنية فقط دون تقديم أي توصية استثمارية."
            if language == "ar"
            else "Answer in English only. Explain technical data only without any investment recommendation."
        )
        tool_data = json.dumps(tool_outputs, ensure_ascii=False, default=str)
        user_prompt = (
            f"السؤال: {question}\n"
            f"الأسهم: {', '.join(tickers)}\n"
            f"<tool_data>\n{tool_data}\n</tool_data>"
        )
        if correction:
            user_prompt = f"{correction}\n\n{user_prompt}"

        system = (
            "You are a financial data explanation assistant. "
            "You MUST only explain the technical data provided by the tools. "
            "NEVER give buy, sell, hold, or any investment advice. "
            f"{lang_instruction}"
        )

        try:
            result = await self._llm.generate_structured(
                system_prompt=system,
                user_prompt=user_prompt,
                output_model=_LLMQAAnswer,
            )
            facts = [
                StockQAFact(
                    label=f.get("label", ""),
                    value=f.get("value", ""),
                    source_tool=f.get("source_tool", "unknown"),
                )
                for f in result.facts
                if f.get("label") and f.get("value")
            ]
            return result.answer, facts
        except Exception:
            logger.exception("LLM Q&A generation failed")
            fallback = (
                "تعذر إنشاء الإجابة حالياً. يرجى المحاولة لاحقاً."
                if language == "ar"
                else "Could not generate answer at this time. Please try again later."
            )
            return fallback, []

    @staticmethod
    def _map_status(
        availability: DataAvailability,
    ) -> str:
        mapping = {
            DataAvailability.AVAILABLE: "ok",
            DataAvailability.PARTIAL: "partial",
            DataAvailability.NOT_FOUND: "not_found",
            DataAvailability.STALE: "partial",
            DataAvailability.UNAVAILABLE: "unavailable",
        }
        return mapping.get(availability, "unavailable")

    @staticmethod
    def _extract_latest_data_date(tool_outputs: list[dict[str, Any]]) -> Any:
        """Extract the most recent data_date from tool outputs."""
        from datetime import date as date_type

        latest = None
        for output in tool_outputs:
            raw = output.get("data_date")
            if raw is None:
                continue
            try:
                d = date_type.fromisoformat(raw) if isinstance(raw, str) else raw
                if latest is None or d > latest:
                    latest = d
            except (ValueError, TypeError):
                continue
        return latest

    @staticmethod
    def _extract_min_freshness(tool_outputs: list[dict[str, Any]]) -> int | None:
        """Return the smallest freshness_seconds from tool outputs."""
        values = [
            o["freshness_seconds"]
            for o in tool_outputs
            if o.get("freshness_seconds") is not None
        ]
        return min(values) if values else None
