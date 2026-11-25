"""Application service for authorized prepared-input Explanation modes."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.explanation.adapters import (
    AdaptedInput,
    adapt_alert,
    adapt_follow_up,
    adapt_recommendation,
)
from app.explanation.evidence import NewsEvidenceRetriever
from app.explanation.generator import ExplanationGenerator
from app.explanation.graph import ExplanationGraph
from app.explanation.interfaces import EvidenceRetriever, LLMClient
from app.explanation.schemas import (
    AlertExplanationRequest,
    FollowUpRequest,
    RecommendationExplanationRequest,
    ExplanationResponse,
)
from app.explanation.schemas import ExplanationLanguage
from app.monitoring.models.alert import Alert
from app.recommendation import repository as recommendation_repository
from app.recommendation.schemas import RecommendationResult
from app.technical_analysis.models import TechnicalSnapshot
from app.technical_analysis.repository import get_snapshot_by_date


class PreparedExplanationService:
    """Run modes 1–3 through evidence retrieval, validation, and memory graph."""

    def __init__(
        self,
        *,
        llm: LLMClient,
        evidence_retriever: EvidenceRetriever,
        checkpointer: Any = None,
    ) -> None:
        self.graph = ExplanationGraph(
            generator=ExplanationGenerator(llm),
            retriever=NewsEvidenceRetriever(evidence_retriever),
            checkpointer=checkpointer,
        )

    async def explain_recommendation(
        self,
        request: RecommendationExplanationRequest,
        *,
        user_id: UUID,
        session: AsyncSession,
    ) -> ExplanationResponse:
        await self._verify_owned_recommendation(
            request.recommendation, user_id=user_id, session=session
        )
        adapted = adapt_recommendation(request)
        adapted = self._ignore_client_evidence(adapted, bool(request.news_evidence), request.language)
        return await self.graph.ainvoke(
            adapted=adapted,
            user_id=str(user_id),
            thread_id=request.thread_id,
            expected_decision=request.recommendation.decision,
        )

    async def explain_alert(
        self,
        request: AlertExplanationRequest,
        *,
        user_id: UUID,
        session: AsyncSession,
    ) -> ExplanationResponse:
        alert_row = await session.scalar(
            select(Alert).where(Alert.id == request.alert.id, Alert.user_id == user_id)
        )
        if alert_row is None:
            raise HTTPException(status_code=404, detail="Alert not found")
        owned_alert = type(request.alert).model_validate(alert_row)
        old_snapshot = None
        new_snapshot = None
        if request.old_snapshot is not None:
            old_snapshot = await get_snapshot_by_date(
                session, owned_alert.ticker, request.old_snapshot.date
            )
        if request.new_snapshot is not None:
            new_snapshot = await get_snapshot_by_date(
                session, owned_alert.ticker, request.new_snapshot.date
            )
        authorized_request = request.model_copy(
            update={
                "alert": owned_alert,
                "old_snapshot": old_snapshot,
                "new_snapshot": new_snapshot,
            }
        )
        adapted = adapt_alert(authorized_request)
        adapted = self._ignore_client_evidence(adapted, bool(request.news_evidence), request.language)
        return await self.graph.ainvoke(
            adapted=adapted,
            user_id=str(user_id),
            thread_id=request.thread_id,
        )

    async def explain_follow_up(
        self,
        request: FollowUpRequest,
        *,
        user_id: UUID,
        session: AsyncSession,
    ) -> ExplanationResponse:
        owned_subject = await self._load_owned_subject(request, user_id=user_id, session=session)
        prior_context = (
            {"authorized_subject": owned_subject}
            if owned_subject is not None
            else request.prior_context
        )
        safe_request = request.model_copy(update={"prior_context": prior_context})
        adapted = adapt_follow_up(safe_request)
        if owned_subject:
            adapted = AdaptedInput(
                mode=adapted.mode,
                ticker=owned_subject.get("ticker", adapted.ticker),
                as_of=adapted.as_of,
                payload=adapted.payload,
                status=adapted.status,
                limitations=adapted.limitations,
            )
        return await self.graph.ainvoke(
            adapted=adapted,
            user_id=str(user_id),
            thread_id=request.thread_id,
        )

    @staticmethod
    def _ignore_client_evidence(
        adapted: AdaptedInput,
        has_client_evidence: bool,
        language: ExplanationLanguage,
    ) -> AdaptedInput:
        if not has_client_evidence:
            return adapted
        limitation = (
            "تم تجاهل الأخبار المرسلة من العميل؛ تُستخدم فقط المصادر التي جرى استرجاعها والتحقق منها."
            if language is ExplanationLanguage.ARABIC
            else "Client-supplied news was ignored; only retrieved sources are used."
        )
        return AdaptedInput(
            mode=adapted.mode,
            ticker=adapted.ticker,
            as_of=adapted.as_of,
            payload=adapted.payload,
            status=adapted.status,
            limitations=(*adapted.limitations, limitation),
        )

    @staticmethod
    async def _verify_owned_recommendation(
        recommendation: RecommendationResult,
        *,
        user_id: UUID,
        session: AsyncSession,
    ) -> None:
        rows = await recommendation_repository.get_recommendation_history(
            session,
            user_id=user_id,
            ticker=recommendation.ticker,
            limit=500,
        )
        matching = next(
            (
                row
                for row in rows
                if row.trading_date == recommendation.trading_date
                and row.snapshot_id == recommendation.snapshot_id
                and row.config_version == recommendation.config_version
                and row.decision == recommendation.decision.value
                and row.confidence == recommendation.confidence.value
                and list(row.blockers or []) == recommendation.reasons
            ),
            None,
        )
        if matching is None:
            raise HTTPException(status_code=404, detail="Recommendation not found")
        if recommendation.snapshot_id is None:
            return
        snapshot = await session.get(TechnicalSnapshot, recommendation.snapshot_id)
        if (
            snapshot is None
            or snapshot.ticker != recommendation.ticker
            or snapshot.date != recommendation.trading_date
            or snapshot.data_quality_status != recommendation.data_quality.price_status
            or snapshot.setup_score != recommendation.setup_score
            or snapshot.regime != recommendation.regime
            or any(
                value != (snapshot.indicators or {}).get(name)
                for name, value in recommendation.indicators.items()
            )
        ):
            raise HTTPException(status_code=404, detail="Recommendation not found")

    @staticmethod
    async def _load_owned_subject(
        request: FollowUpRequest,
        *,
        user_id: UUID,
        session: AsyncSession,
    ) -> dict[str, Any] | None:
        if request.subject_id is None:
            if request.subject_type in {"recommendation", "alert"}:
                raise HTTPException(
                    status_code=422,
                    detail="subject_id is required for recommendation or alert follow-up",
                )
            return None

        if request.subject_type == "stock_qa":
            raise HTTPException(
                status_code=422,
                detail="Stock Q&A follow-up uses the user-scoped thread_id, not subject_id",
            )

        if request.subject_type == "recommendation":
            row = await recommendation_repository.get_recommendation_by_id(
                session, user_id=user_id, recommendation_id=request.subject_id
            )
            if row is None:
                raise HTTPException(status_code=404, detail="Recommendation not found")
            return {
                "subject_type": "recommendation",
                "id": str(row.id),
                "ticker": row.ticker,
                "trading_date": row.trading_date.isoformat() if row.trading_date else None,
                "decision": row.decision,
                "config_version": row.config_version,
                "confidence": row.confidence,
                "blockers": list(row.blockers or []),
            }

        if request.subject_type == "alert":
            statement = select(Alert).where(
                Alert.id == request.subject_id,
                Alert.user_id == user_id,
            )
            row = await session.scalar(statement)
            if row is None:
                raise HTTPException(status_code=404, detail="Alert not found")
            return {
                "subject_type": "alert",
                "id": str(row.id),
                "ticker": row.ticker,
                "alert_type": row.alert_type,
                "severity": row.severity,
                "reason": row.reason,
                "evidence": row.evidence,
                "current_value": row.current_value,
                "threshold_value": row.threshold_value,
                "created_at": row.created_at.isoformat(),
            }
        return None
