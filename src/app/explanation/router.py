"""Authenticated Explanation Agent routes and Stock Q&A integration."""

from __future__ import annotations

import re
from typing import Annotated, Protocol
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy.ext.asyncio import AsyncSession

from app.explanation.interfaces import LLMClient
from app.explanation.intent_splitter import IntentSplit, QuestionIntent, split_question_intent
from app.explanation.llm import GroqStructuredLLMClient, StructuredLLMError
from app.explanation.schemas import (
    AlertExplanationRequest,
    ExplanationLanguage,
    ExplanationResponse,
    FollowUpRequest,
    RecommendationExplanationRequest,
    StockQARequest,
    StockQAResponse,
)
from app.explanation.stock_qa import StockQAAgent
from app.explanation.tools import build_stock_qa_tools
from app.api.middleware import check_explanation_rate_limit
from app.monitoring.dependencies import get_current_user_id
from app.recommendation import repository as recommendation_repository
from app.recommendation.dependencies import get_recommendation_session
from app.recommendation.decision import evaluate_decision
from app.recommendation.inputs import load_recommendation_inputs
from app.recommendation.results import build_recommendation_result
from app.recommendation.schemas import RecommendationEvaluationResponse


router = APIRouter(
    prefix="/api/v1/explanations",
    tags=["explanations"],
    dependencies=[Depends(check_explanation_rate_limit)],
)
UserId = Annotated[UUID, Depends(get_current_user_id)]
SessionDep = Annotated[AsyncSession, Depends(get_recommendation_session)]


class ExplanationCoreService(Protocol):
    """Member A service contract consumed by the shared typed API routes."""

    async def explain_recommendation(
        self,
        request: RecommendationExplanationRequest,
        *,
        user_id: UUID,
        session: AsyncSession,
    ) -> ExplanationResponse: ...

    async def explain_alert(
        self,
        request: AlertExplanationRequest,
        *,
        user_id: UUID,
        session: AsyncSession,
    ) -> ExplanationResponse: ...

    async def explain_follow_up(
        self,
        request: FollowUpRequest,
        *,
        user_id: UUID,
        session: AsyncSession,
    ) -> ExplanationResponse: ...


def get_explanation_core_service(request: Request) -> ExplanationCoreService:
    service = getattr(request.app.state, "explanation_core_service", None)
    if service is None:
        raise HTTPException(status_code=503, detail="Explanation service is not configured")
    return service


def get_explanation_llm() -> LLMClient:
    try:
        return GroqStructuredLLMClient.from_settings()
    except StructuredLLMError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


CoreService = Annotated[ExplanationCoreService, Depends(get_explanation_core_service)]
LLMDep = Annotated[LLMClient, Depends(get_explanation_llm)]


class QuestionRequest(BaseModel):
    """Natural-language question envelope for mixed-intent dispatch."""

    model_config = ConfigDict(extra="forbid")

    question: str = Field(min_length=1, max_length=4000)
    tickers: list[str] = Field(min_length=1, max_length=5)
    language: ExplanationLanguage = ExplanationLanguage.ARABIC

    @model_validator(mode="after")
    def normalize_request(self) -> "QuestionRequest":
        self.question = self.question.strip()
        if not self.question:
            raise ValueError("question must not be blank")
        if any(not ticker.strip() for ticker in self.tickers):
            raise ValueError("tickers must be non-empty and unique")
        normalized = [ticker.strip().upper() for ticker in self.tickers if ticker.strip()]
        if (
            not normalized
            or len(set(normalized)) != len(normalized)
            or any(not re.fullmatch(r"[A-Z0-9][A-Z0-9.-]{0,31}", ticker) for ticker in normalized)
        ):
            raise ValueError("tickers must be non-empty and unique")
        self.tickers = normalized
        if "language" not in self.model_fields_set:
            self.language = (
                ExplanationLanguage.ARABIC
                if re.search(r"[\u0600-\u06ff]", self.question)
                else ExplanationLanguage.ENGLISH
            )
        return self


class RoutedQuestionResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    intent: QuestionIntent
    descriptive_question: str | None = None
    recommendation_question: str | None = None
    stock_qa: StockQAResponse | None = None
    recommendations: list[RecommendationEvaluationResponse] = Field(default_factory=list)
    clarification: str | None = None


async def _run_stock_qa(
    request: StockQARequest,
    *,
    session: AsyncSession,
    llm: LLMClient,
) -> StockQAResponse:
    agent = StockQAAgent(llm=llm, tools=build_stock_qa_tools(session=session))
    return await agent.ainvoke(request)


@router.post("/recommendation", response_model=ExplanationResponse)
async def explain_recommendation(
    body: RecommendationExplanationRequest,
    user_id: UserId,
    session: SessionDep,
    service: CoreService,
) -> ExplanationResponse:
    result = await service.explain_recommendation(body, user_id=user_id, session=session)
    if result.explanation_type != "recommendation":
        raise HTTPException(status_code=502, detail="Explanation service returned the wrong response type")
    if result.decision != body.recommendation.decision:
        raise HTTPException(status_code=502, detail="Explanation service changed the upstream decision")
    return result


@router.post("/alert", response_model=ExplanationResponse)
async def explain_alert(
    body: AlertExplanationRequest,
    user_id: UserId,
    session: SessionDep,
    service: CoreService,
) -> ExplanationResponse:
    if body.alert.user_id != user_id:
        raise HTTPException(status_code=404, detail="Alert not found")
    result = await service.explain_alert(body, user_id=user_id, session=session)
    if result.explanation_type != "alert":
        raise HTTPException(status_code=502, detail="Explanation service returned the wrong response type")
    return result


@router.post("/follow-up", response_model=ExplanationResponse)
async def explain_follow_up(
    body: FollowUpRequest,
    user_id: UserId,
    session: SessionDep,
    service: CoreService,
) -> ExplanationResponse:
    result = await service.explain_follow_up(body, user_id=user_id, session=session)
    if result.explanation_type != "follow_up":
        raise HTTPException(status_code=502, detail="Explanation service returned the wrong response type")
    return result


@router.post("/stock-qa", response_model=StockQAResponse)
async def answer_stock_question(
    body: StockQARequest,
    user_id: UserId,
    session: SessionDep,
    llm: LLMDep,
) -> StockQAResponse:
    del user_id  # Authentication is required; stock Q&A reads public market data only.
    try:
        return await _run_stock_qa(body, session=session, llm=llm)
    except StructuredLLMError as exc:
        raise HTTPException(status_code=502, detail="Stock Q&A generation failed") from exc


@router.post("/question", response_model=RoutedQuestionResponse)
async def route_question(
    body: QuestionRequest,
    user_id: UserId,
    session: SessionDep,
    llm: LLMDep,
) -> RoutedQuestionResponse:
    split: IntentSplit = split_question_intent(body.question)
    result = RoutedQuestionResponse(
        intent=split.intent,
        descriptive_question=split.descriptive_question,
        recommendation_question=split.recommendation_question,
    )
    if split.intent is QuestionIntent.AMBIGUOUS:
        result.clarification = (
            "يرجى توضيح ما إذا كان السؤال يطلب وصف البيانات أم تقييماً توصوياً."
            if body.language is ExplanationLanguage.ARABIC
            else "Please clarify whether you want a description of the data or an investment recommendation."
        )
        return result
    if split.descriptive_question:
        result.stock_qa = await _run_stock_qa(
            StockQARequest(
                question=split.descriptive_question,
                tickers=body.tickers,
                language=body.language,
            ),
            session=session,
            llm=llm,
        )
    if split.recommendation_question:
        for ticker in body.tickers:
            inputs = await load_recommendation_inputs(session, user_id=user_id, ticker=ticker)
            evaluation = evaluate_decision(inputs)
            recommendation = build_recommendation_result(inputs, evaluation)
            audit = await recommendation_repository.save_recommendation_log(
                session, user_id=user_id, result=recommendation
            )
            result.recommendations.append(
                RecommendationEvaluationResponse(
                    recommendation_id=audit.id,
                    created_at=audit.created_at,
                    result=recommendation,
                )
            )
    return result
