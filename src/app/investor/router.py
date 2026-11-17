"""FastAPI routes for the Investor Agent (Spec Section 10).

Mounted under ``/api/v1/investor``. Every route is scoped to the caller via
``get_current_user_id`` (the shared ``X-User-ID`` stand-in until PLAN-003
ships real authentication).
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from sqlalchemy.ext.asyncio import AsyncSession

from app.investor import repository, service
from app.investor.memory import (
    FoundationalPreferenceError,
    PostgresPreferenceMemory,
    PreferenceMemory,
    ProfileReviewStatus,
    RecommendationFeedback,
    record_recommendation_feedback,
)
from app.investor.schemas import (
    ConfirmedProfileResponse,
    ConstraintsUpdateRequest,
    InterviewMessageRequest,
    InterviewMessageResponse,
    InvestorProfilePayload,
    LearnedPreferenceRead,
    ProfileAuditLogRead,
    RecommendationFeedbackRequest,
    SessionConfirmRequest,
)
from app.monitoring.dependencies import get_current_user_id

router = APIRouter(prefix="/api/v1/investor", tags=["investor"])

UserId = Annotated[UUID, Depends(get_current_user_id)]


async def get_db_session() -> AsyncIterator[AsyncSession]:
    """Yield a session that commits on success and rolls back on error."""
    from app.db.session import SessionLocal

    async with SessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


def get_interview_graph(request: Request) -> Any:
    """Return the compiled interview graph built during app startup."""
    graph = getattr(request.app.state, "investor_graph", None)
    if graph is None:
        raise HTTPException(status_code=503, detail="Investor interview is not available")
    return graph


def get_preference_memory() -> PreferenceMemory:
    return PostgresPreferenceMemory()


DbSession = Annotated[AsyncSession, Depends(get_db_session)]
Graph = Annotated[Any, Depends(get_interview_graph)]
Memory = Annotated[PreferenceMemory, Depends(get_preference_memory)]


def _raise_http(exc: service.InvestorServiceError) -> None:
    raise HTTPException(status_code=exc.status_code, detail=exc.detail) from exc


# --- Interview --------------------------------------------------------------


@router.post("/interview/message", response_model=InterviewMessageResponse)
async def post_interview_message(
    req: InterviewMessageRequest,
    user_id: UserId,
    graph: Graph,
    session: DbSession,
    memory: Memory,
) -> InterviewMessageResponse:
    """Send a user answer and receive the next question or the HITL summary card."""
    try:
        return await service.handle_interview_message(
            graph,
            session,
            memory,
            user_id=user_id,
            session_id=req.session_id,
            message=req.message,
        )
    except service.InvestorServiceError as exc:
        _raise_http(exc)
        raise


@router.get("/interview/sessions/{session_id}", response_model=InterviewMessageResponse)
async def get_interview_session(
    session_id: UUID,
    user_id: UserId,
    graph: Graph,
) -> InterviewMessageResponse:
    """Return the latest state of an interview so the client can resume it."""
    try:
        return await service.get_interview_session(
            graph, user_id=user_id, session_id=session_id
        )
    except service.InvestorServiceError as exc:
        _raise_http(exc)
        raise


# --- Profile ----------------------------------------------------------------


@router.get("/profile/active", response_model=InvestorProfilePayload)
async def get_active_profile(user_id: UserId, session: DbSession) -> InvestorProfilePayload:
    """Active confirmed profile. Consumed by the Dashboard and Recommendation Engine."""
    payload = await repository.get_active_profile_payload(session, user_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="No active investor profile")
    return payload


@router.post("/profile/confirm", response_model=ConfirmedProfileResponse)
async def confirm_profile(
    req: SessionConfirmRequest,
    user_id: UserId,
    graph: Graph,
    session: DbSession,
) -> ConfirmedProfileResponse:
    """HITL confirmation: activate the reviewed (and optionally edited) profile."""
    try:
        return await service.confirm_session_profile(
            graph, session, user_id=user_id, request=req
        )
    except service.InvestorServiceError as exc:
        _raise_http(exc)
        raise


@router.patch("/profile/constraints", response_model=InvestorProfilePayload)
async def update_constraints(
    req: ConstraintsUpdateRequest,
    user_id: UserId,
    session: DbSession,
) -> InvestorProfilePayload:
    """Update excluded/preferred sectors and excluded tickers without re-interviewing."""
    profile = await repository.update_profile_constraints(session, user_id, req)
    if profile is None:
        raise HTTPException(status_code=404, detail="No active investor profile")
    return InvestorProfilePayload.model_validate(profile)


@router.get("/profile/history", response_model=list[InvestorProfilePayload])
async def get_profile_history(user_id: UserId, session: DbSession) -> list[InvestorProfilePayload]:
    """All confirmed profile versions, newest first."""
    profiles = await repository.get_profile_history(session, user_id)
    return [InvestorProfilePayload.model_validate(p) for p in profiles]


@router.get("/profile/audit", response_model=list[ProfileAuditLogRead])
async def get_profile_audit(
    user_id: UserId,
    session: DbSession,
    limit: int = Query(default=50, ge=1, le=200),
) -> list[ProfileAuditLogRead]:
    """Immutable audit trail of confirmed profile changes."""
    logs = await repository.list_audit_logs(session, user_id, limit=limit)
    return [ProfileAuditLogRead.model_validate(log) for log in logs]


@router.get("/profile/review-status", response_model=ProfileReviewStatus)
async def get_review_status(
    user_id: UserId,
    session: DbSession,
    memory: Memory,
) -> ProfileReviewStatus:
    """Re-profiling suggestions (stale profile, behavior drift, life events)."""
    return await service.get_review_status(session, memory, user_id=user_id)


# --- Memory -----------------------------------------------------------------


@router.get("/preferences", response_model=list[LearnedPreferenceRead])
async def list_preferences(
    user_id: UserId,
    session: DbSession,
    memory: Memory,
    validated_only: bool = Query(default=False),
) -> list[LearnedPreferenceRead]:
    """Learned preferences. These never change the active profile by themselves."""
    prefs = await memory.recall(session, user_id, validated_only=validated_only)
    return [LearnedPreferenceRead.model_validate(p) for p in prefs]


@router.post("/feedback", response_model=LearnedPreferenceRead, status_code=201)
async def post_recommendation_feedback(
    req: RecommendationFeedbackRequest,
    user_id: UserId,
    session: DbSession,
    memory: Memory,
) -> LearnedPreferenceRead:
    """Record a reaction to a recommendation or alert (episodic memory)."""
    try:
        pref = await record_recommendation_feedback(
            memory,
            session,
            user_id,
            RecommendationFeedback(req.feedback),
            ticker=req.ticker,
        )
    except FoundationalPreferenceError as exc:  # pragma: no cover - defensive
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return LearnedPreferenceRead.model_validate(pref)
