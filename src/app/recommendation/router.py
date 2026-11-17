"""Authenticated recommendation evaluation and audit read routes."""

from __future__ import annotations

from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.monitoring.dependencies import get_current_user_id
from app.recommendation import repository
from app.recommendation.decision import evaluate_decision
from app.recommendation.dependencies import get_recommendation_session
from app.recommendation.inputs import load_recommendation_inputs
from app.recommendation.results import build_recommendation_result
from app.recommendation.schemas import (
    RecommendationAuditRead,
    RecommendationEvaluationResponse,
    RecommendationEvaluateRequest,
    RecommendationHistoryRead,
)


router = APIRouter(prefix="/api/v1/recommendations", tags=["recommendations"])

UserId = Annotated[UUID, Depends(get_current_user_id)]
SessionDep = Annotated[AsyncSession, Depends(get_recommendation_session)]


@router.post("", response_model=RecommendationEvaluationResponse)
async def evaluate_recommendation(
    request: RecommendationEvaluateRequest,
    user_id: UserId,
    session: SessionDep,
) -> RecommendationEvaluationResponse:
    """Evaluate stored profile and snapshot data, then persist the audit row."""
    inputs = await load_recommendation_inputs(
        session,
        user_id=user_id,
        ticker=request.ticker,
    )
    evaluation = evaluate_decision(inputs)
    result = build_recommendation_result(inputs, evaluation)
    audit = await repository.save_recommendation_log(
        session,
        user_id=user_id,
        result=result,
    )
    return RecommendationEvaluationResponse(
        recommendation_id=audit.id,
        created_at=audit.created_at,
        result=result,
    )


@router.get("/history", response_model=RecommendationHistoryRead)
async def read_recommendation_history(
    user_id: UserId,
    session: SessionDep,
    ticker: str | None = Query(default=None, min_length=1, max_length=32),
    limit: int = Query(default=50, ge=1, le=500),
) -> RecommendationHistoryRead:
    rows = await repository.get_recommendation_history(
        session,
        user_id=user_id,
        ticker=ticker,
        limit=limit,
    )
    return RecommendationHistoryRead(
        count=len(rows),
        recommendations=[RecommendationAuditRead.model_validate(row) for row in rows],
    )


@router.get("/{recommendation_id}", response_model=RecommendationAuditRead)
async def read_recommendation(
    recommendation_id: UUID,
    user_id: UserId,
    session: SessionDep,
) -> RecommendationAuditRead:
    row = await repository.get_recommendation_by_id(
        session,
        user_id=user_id,
        recommendation_id=recommendation_id,
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Recommendation not found")
    return RecommendationAuditRead.model_validate(row)
