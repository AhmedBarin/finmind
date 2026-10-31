from app.db.session import SessionLocal
from app.news.service import NewsService
from app.news.sources.registry import create_default_registry


def get_news_service() -> NewsService:
    return NewsService(
        session_factory=SessionLocal,
        registry=create_default_registry(),
    )