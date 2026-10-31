from datetime import datetime

from fastapi import APIRouter, Depends, Query

from app.core.dependencies import get_news_service
from app.news.schemas import NewsArticleRead
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