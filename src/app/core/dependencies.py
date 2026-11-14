from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.news.analysis_service import NewsAnalysisService
from app.news.service import NewsService
from app.news.sources.registry import create_default_registry
from app.agents.news_agent.tools import NewsAgentTools
from app.agents.news_agent.analysis_tools import NewsAnalysisTools


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def get_news_service() -> NewsService:
    return NewsService(
        session_factory=SessionLocal,
        registry=create_default_registry(),
    )


def get_news_analysis_service() -> NewsAnalysisService:
    return NewsAnalysisService()


def get_news_agent_tools() -> NewsAgentTools:
    return NewsAgentTools(get_news_service())


def get_news_analysis_tools() -> NewsAnalysisTools:
    return NewsAnalysisTools(get_news_analysis_service())
