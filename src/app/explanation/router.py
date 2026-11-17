"""Explanation Agent routes: Stock Q&A (PLAN-014) and alert explanations (PLAN-013)."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db_session
from app.core.security import get_current_principal, get_current_user_id, rate_limit
from app.explanation.alerts.repository import get_alert_for_user, get_alert_snapshots
from app.explanation.alerts.schemas import (
    AlertExplanationInput,
    AlertExplanationResponse,
    AlertInputError,
)
from app.explanation.alerts.service import AlertExplanationService
from app.explanation.config import get_explanation_settings
from app.explanation.llm import GroqExplanationLLM
from app.explanation.stock_qa.schemas import StockQARequest, StockQAResponse
from app.explanation.stock_qa.service import StockQAService
from app.explanation.stock_qa.tools import StockQATools

router = APIRouter(
    prefix="/api/v1/explanations",
    tags=["explanations"],
    dependencies=[Depends(get_current_principal)],
)


@lru_cache
def get_stock_qa_service() -> StockQAService:
    settings = get_explanation_settings()
    return StockQAService(
        GroqExplanationLLM.from_settings(explanation=settings),
        max_snapshot_age_days=settings.max_snapshot_age_days,
    )


@router.post(
    "/stock-qa",
    response_model=StockQAResponse,
    dependencies=[
        Depends(rate_limit("stock_qa", get_explanation_settings().rate_limit_per_minute))
    ],
)
async def ask_stock_question(
    request: StockQARequest,
    session: Annotated[AsyncSession, Depends(get_db_session)],
    service: Annotated[StockQAService, Depends(get_stock_qa_service)],
) -> StockQAResponse:
    """Answer a descriptive question about stored technical data for 1–5 tickers.

    Advice-seeking parts of the question are returned in
    ``routed_to_recommendation`` and are not answered.
    """
    return await service.answer(StockQATools(session), request)


@lru_cache
def get_alert_explanation_service() -> AlertExplanationService:
    return AlertExplanationService(
        GroqExplanationLLM.from_settings(explanation=get_explanation_settings())
    )


@router.post(
    "/alerts/{alert_id}",
    response_model=AlertExplanationResponse,
    dependencies=[
        Depends(
            rate_limit(
                "alert_explanation", get_explanation_settings().rate_limit_per_minute
            )
        )
    ],
)
async def explain_alert(
    alert_id: UUID,
    user_id: Annotated[UUID, Depends(get_current_user_id)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    service: Annotated[AlertExplanationService, Depends(get_alert_explanation_service)],
) -> AlertExplanationResponse:
    """Explain, in Arabic, why one of the caller's monitoring alerts triggered.

    The alert is read, never modified. Alerts owned by someone else are 404.
    """
    alert = await get_alert_for_user(session, alert_id, user_id)
    if alert is None:
        raise HTTPException(status_code=404, detail="Alert not found")
    try:
        inp = AlertExplanationInput.from_alert(alert)
    except AlertInputError:
        raise HTTPException(status_code=422, detail="This alert cannot be explained") from None
    current, previous = await get_alert_snapshots(session, inp.ticker, inp.data_date)
    return await service.explain(inp, current, previous)
