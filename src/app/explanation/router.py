"""Explanation Agent routes. Stock Q&A is the first mode exposed (PLAN-014)."""

from __future__ import annotations

from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import get_db_session
from app.core.security import get_current_principal, rate_limit
from app.explanation.config import get_explanation_settings
from app.explanation.stock_qa.generator import GroqStockQAGenerator
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
        GroqStockQAGenerator.from_settings(explanation=settings),
        max_snapshot_age_days=settings.max_snapshot_age_days,
    )


@router.post(
    "/stock-qa",
    response_model=StockQAResponse,
    dependencies=[
        Depends(rate_limit("stock_qa", get_explanation_settings().qa_rate_limit_per_minute))
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
