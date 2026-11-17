from collections.abc import AsyncIterator

from fastapi import Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.db.session import SessionLocal
from app.news.analysis_service import NewsAnalysisService
from app.news.service import NewsService
from app.news.sources.registry import create_default_registry
from app.agents.news_agent.tools import NewsAgentTools
from app.agents.news_agent.analysis_tools import NewsAnalysisTools
from app.agents.news_agent.agent import LangChainNewsAgent
from app.agents.news_agent.retrieval_tools import NewsRetrievalTools


async def get_db_session() -> AsyncIterator[AsyncSession]:
    async with SessionLocal() as session:
        yield session


def get_news_service() -> NewsService:
    return NewsService(session_factory=SessionLocal, registry=create_default_registry())


def get_news_analysis_service() -> NewsAnalysisService:
    return NewsAnalysisService()


def get_news_agent_tools() -> NewsAgentTools:
    return NewsAgentTools(get_news_service())


def get_news_analysis_tools() -> NewsAnalysisTools:
    return NewsAnalysisTools(get_news_analysis_service())


def get_news_retrieval_tools() -> object:
    try:
        from app.news.retrieval import PersistentChromaNewsVectorIndex
        index = PersistentChromaNewsVectorIndex(path=settings.news_vector_store_path, collection_name=settings.news_vector_collection)
        return NewsRetrievalTools(index)
    except (ImportError, RuntimeError) as exc:
        error_message = str(exc)

        class UnavailableRetrievalTools:
            def get_annual_report_evidence(self, request):
                raise RuntimeError(error_message)

            def retrieve_similar_news(self, request):
                raise RuntimeError(error_message)

        return UnavailableRetrievalTools()


def get_news_agent(
    session: AsyncSession = Depends(get_db_session),
    news_tools: NewsAgentTools = Depends(get_news_agent_tools),
    retrieval_tools: object = Depends(get_news_retrieval_tools),
    analysis_tools: NewsAnalysisTools = Depends(get_news_analysis_tools),
) -> LangChainNewsAgent:
    if not settings.news_analysis_model:
        raise RuntimeError("NEWS_ANALYSIS_MODEL is not configured")
    return LangChainNewsAgent(session=session, news_tools=news_tools, retrieval_tools=retrieval_tools, analysis_tools=analysis_tools, model_name=settings.news_analysis_model)
