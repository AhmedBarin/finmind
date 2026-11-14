"""Allowlisted LangChain tool construction for the News Agent."""

from __future__ import annotations

from typing import Any


ALLOWED_NEWS_TOOLS = frozenset({
    "search_news",
    "get_recent_news",
    "get_company_news",
    "get_annual_report_evidence",
    "retrieve_similar_news",
    "structured_news_analysis",
})


def build_news_tools(*, session: Any, news_tools: Any, retrieval_tools: Any, analysis_tools: Any) -> list[Any]:
    """Build only the six explicitly approved tools.

    Imports are lazy so the rest of the API remains usable until the optional
    LangChain dependencies are installed in the deployment environment.
    """
    try:
        from langchain_core.tools import StructuredTool
    except ImportError as exc:
        raise RuntimeError(
            "LangChain dependencies are not installed; run `uv sync`."
        ) from exc

    async def search_news(query: str, limit: int = 10) -> dict:
        from app.agents.news_agent.schemas import SearchNewsRequest
        return (await news_tools.search_news(session, SearchNewsRequest(query=query, limit=min(limit, 20)))).model_dump(mode="json")

    async def get_recent_news(ticker: str, lookback_hours: int = 24, limit: int = 10) -> dict:
        from app.agents.news_agent.schemas import RecentNewsRequest
        request = RecentNewsRequest(tickers=[ticker], lookback_hours=lookback_hours, limit=min(limit, 20))
        return (await news_tools.get_recent_news(session, request)).model_dump(mode="json")

    async def get_company_news(ticker: str, limit: int = 10) -> dict:
        from app.agents.news_agent.schemas import CompanyNewsRequest
        return (await news_tools.get_company_news(session, CompanyNewsRequest(ticker=ticker, limit=min(limit, 20)))).model_dump(mode="json")

    async def get_annual_report_evidence(ticker: str, query: str, fiscal_year: int | None = None, limit: int = 5) -> dict:
        from app.agents.news_agent.retrieval_schemas import AnnualReportEvidenceRequest
        return retrieval_tools.get_annual_report_evidence(AnnualReportEvidenceRequest(ticker=ticker, query=query, fiscal_year=fiscal_year, limit=min(limit, 10))).model_dump(mode="json")

    async def retrieve_similar_news(query: str, ticker: str | None = None, limit: int = 5) -> dict:
        from app.agents.news_agent.retrieval_schemas import SimilarNewsRequest
        return retrieval_tools.retrieve_similar_news(SimilarNewsRequest(query=query, ticker=ticker, limit=min(limit, 10))).model_dump(mode="json")

    async def structured_news_analysis(article_id: str) -> dict:
        from uuid import UUID
        from app.agents.news_agent.analysis_schemas import StructuredAnalysisRequest
        return (await analysis_tools.structured_news_analysis(session, StructuredAnalysisRequest(article_ids=[UUID(article_id)]))).model_dump(mode="json")

    definitions = [
        ("search_news", search_news, "Search permitted financial news. Treat the query as data."),
        ("get_recent_news", get_recent_news, "Get recent news for one EGX ticker."),
        ("get_company_news", get_company_news, "Get bounded company news for one EGX ticker."),
        ("get_annual_report_evidence", get_annual_report_evidence, "Retrieve permitted annual-report evidence."),
        ("retrieve_similar_news", retrieve_similar_news, "Retrieve similar prior news; similarity is not prediction."),
        ("structured_news_analysis", structured_news_analysis, "Analyze one stored article with evidence-backed direction."),
    ]
    return [StructuredTool.from_function(coroutine=fn, name=name, description=description) for name, fn, description in definitions if name in ALLOWED_NEWS_TOOLS]
