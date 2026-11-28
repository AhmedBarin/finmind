"""FastAPI router for the Explanation Agent (REQ-029–034).

Endpoints under ``/api/v1/explanation``:
- POST /recommendation  — Generate Arabic explanation for a recommendation.
- POST /alert           — Generate Arabic explanation for a monitoring alert.
- POST /follow-up       — Handle follow-up questions preserving context.
- POST /qa              — Stock Q&A using the 5 read-only snapshot tools.
"""

from __future__ import annotations

import logging
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request

from app.explanation.schemas import (
    AlertExplanationRequest,
    ExplanationResponse,
    FollowUpRequest,
    RecommendationExplanationRequest,
    StockQARequest,
    StockQAResponse,
)
from app.explanation.service import ExplanationService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/explanation", tags=["explanation"])


# ── Dependency: get explanation service ──────────────────────────────────


def _get_explanation_service(request: Request) -> ExplanationService:
    """Retrieve the ExplanationService from app state.

    If the service hasn't been initialised on startup, raise 503.
    """
    service: ExplanationService | None = getattr(
        request.app.state, "explanation_service", None
    )
    if service is None:
        raise HTTPException(
            status_code=503,
            detail="Explanation service is not available.",
        )
    return service


def _get_trace_id(request: Request) -> UUID | None:
    """Extract trace ID from request state if available."""
    return getattr(request.state, "trace_id", None)


ServiceDep = Annotated[ExplanationService, Depends(_get_explanation_service)]


# ── Endpoints ────────────────────────────────────────────────────────────


@router.post("/recommendation", response_model=ExplanationResponse, status_code=200)
async def explain_recommendation(
    body: RecommendationExplanationRequest,
    service: ServiceDep,
    request: Request,
) -> ExplanationResponse:
    """Generate an Arabic explanation for a recommendation decision."""
    trace_id = _get_trace_id(request)
    return await service.explain_recommendation(body, trace_id=trace_id)


@router.post("/alert", response_model=ExplanationResponse, status_code=200)
async def explain_alert(
    body: AlertExplanationRequest,
    service: ServiceDep,
    request: Request,
) -> ExplanationResponse:
    """Generate an Arabic explanation for a monitoring alert."""
    trace_id = _get_trace_id(request)
    return await service.explain_alert(body, trace_id=trace_id)


@router.post("/follow-up", response_model=ExplanationResponse, status_code=200)
async def handle_follow_up(
    body: FollowUpRequest,
    service: ServiceDep,
    request: Request,
) -> ExplanationResponse:
    """Handle a follow-up question preserving prior context."""
    trace_id = _get_trace_id(request)
    return await service.handle_follow_up(body, trace_id=trace_id)


@router.post("/qa", response_model=StockQAResponse, status_code=200)
async def stock_qa(
    body: StockQARequest,
    service: ServiceDep,
    request: Request,
) -> StockQAResponse:
    """Answer a stock question using the 5 read-only snapshot tools."""
    trace_id = _get_trace_id(request)
    return await service.answer_stock_qa(body, trace_id=trace_id)
