from datetime import datetime
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.dependencies import (
    get_db_session,
    get_news_analysis_service,
    get_news_service,
)
from app.news.analysis_service import NewsAnalysisService
from app.news.groq_client import GroqAnalysisError
from app.news.schemas import NewsAnalysisRead, NewsArticleRead
from app.news.service import NewsService


router = APIRouter(prefix="/news", tags=["news"])


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
