from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.session import SessionLocal
from app.news.analysis_service import NewsAnalysisService
from app.news.service import NewsService
from app.news.sources.registry import create_default_registry
from app.agents.news_agent.tools import NewsAgentTools
from app.agents.news_agent.analysis_tools import NewsAnalysisTools
from app.agents.news_agent.agent import LangChainNewsAgent
from app.core.config import settings
from app.core.security import require_news_agent_auth


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


def get_news_retrieval_tools() -> object:
    try:
        from app.agents.news_agent.retrieval_tools import NewsRetrievalTools
        from app.news.retrieval import InMemoryNewsVectorIndex
    except ImportError:
        class UnavailableRetrievalTools:
            def get_annual_report_evidence(self, request):
                raise RuntimeError("News retrieval tools are not installed")

            def retrieve_similar_news(self, request):
                raise RuntimeError("News retrieval tools are not installed")

        return UnavailableRetrievalTools()
    # Production can replace this dependency with a persistent Chroma collection.
    return NewsRetrievalTools(InMemoryNewsVectorIndex())


def get_news_agent(
    session: AsyncSession = Depends(get_db_session),
    news_tools: NewsAgentTools = Depends(get_news_agent_tools),
    retrieval_tools: object = Depends(get_news_retrieval_tools),
    analysis_tools: NewsAnalysisTools = Depends(get_news_analysis_tools),
) -> LangChainNewsAgent:
    if not settings.news_analysis_model:
        raise RuntimeError("NEWS_ANALYSIS_MODEL is not configured")
    return LangChainNewsAgent(
        session=session,
        news_tools=news_tools,
        retrieval_tools=retrieval_tools,
        analysis_tools=analysis_tools,
        model_name=settings.news_analysis_model,
    )
