from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    get_db_session,
    get_news_agent_tools,
    get_news_analysis_service,
    get_news_analysis_tools,
    get_news_service,
)
from app.news.analysis_service import NewsAnalysisService
from app.news.groq_client import GroqAnalysisError
from app.news.schemas import NewsAnalysisRead, NewsArticleRead
from app.news.service import NewsService
from app.agents.news_agent.schemas import (
    CompanyNewsRequest,
    RecentNewsRequest,
    SearchNewsRequest,
    ToolResponse,
)
from app.agents.news_agent.tools import NewsAgentTools
from app.agents.news_agent.analysis_schemas import StructuredAnalysisRequest, StructuredAnalysisResponse
from app.agents.news_agent.analysis_tools import NewsAnalysisTools


router = APIRouter(prefix="/news", tags=["news"])


@router.post("/analyze", response_model=StructuredAnalysisResponse)
async def structured_news_analysis_tool(
    request: StructuredAnalysisRequest,
    session: AsyncSession = Depends(get_db_session),
    tools: NewsAnalysisTools = Depends(get_news_analysis_tools),
) -> StructuredAnalysisResponse:
    return await tools.structured_news_analysis(session, request)


@router.post("/search", response_model=ToolResponse)
async def search_news_tool(
    request: SearchNewsRequest,
    session: AsyncSession = Depends(get_db_session),
    tools: NewsAgentTools = Depends(get_news_agent_tools),
) -> ToolResponse:
    try:
        return await tools.search_news(session, request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/recent", response_model=ToolResponse)
async def recent_news_tool(
    request: RecentNewsRequest,
    session: AsyncSession = Depends(get_db_session),
    tools: NewsAgentTools = Depends(get_news_agent_tools),
) -> ToolResponse:
    try:
        return await tools.get_recent_news(session, request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/companies/{ticker}/news", response_model=ToolResponse)
async def company_news_tool(
    ticker: str,
    request: CompanyNewsRequest,
    session: AsyncSession = Depends(get_db_session),
    tools: NewsAgentTools = Depends(get_news_agent_tools),
) -> ToolResponse:
    request.ticker = ticker
    try:
        return await tools.get_company_news(session, request)
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/articles", response_model=list[NewsArticleRead])
async def get_news_articles(
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    source_key: str | None = None,
    since: datetime | None = None,
    service: NewsService = Depends(get_news_service),
) -> list[NewsArticleRead]:
    return await service.list_articles(
        limit=limit,
        offset=offset,
        source_key=source_key,
        since=since,
    )


@router.post(
    "/articles/{article_id}/analysis",
    response_model=NewsAnalysisRead,
)
async def analyze_news_article(
    article_id: UUID,
    company_id: UUID | None = None,
    session: AsyncSession = Depends(get_db_session),
    service: NewsAnalysisService = Depends(get_news_analysis_service),
) -> NewsAnalysisRead:
    """Analyze one stored article, optionally relative to a linked company."""

    try:
        result = await service.analyze_article(
            session,
            article_id=article_id,
            company_id=company_id,
        )
        await session.commit()
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except GroqAnalysisError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return result
