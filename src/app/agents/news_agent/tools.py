"""News Agent tools. They delegate to NewsService and never access the DB directly."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.news.service import NewsService
from app.agents.news_agent.schemas import (
    CompanyNewsRequest,
    RecentNewsRequest,
    SearchNewsRequest,
    ToolResponse,
    ToolStatus,
)


class NewsAgentTools:
    def __init__(self, service: NewsService) -> None:
        self.service = service

    async def search_news(self, session: AsyncSession, request: SearchNewsRequest) -> ToolResponse:
        data = await self.service.search_news(session, request)
        return self._response(data, warnings=["Results are limited to permitted article evidence."])

    async def get_recent_news(self, session: AsyncSession, request: RecentNewsRequest) -> ToolResponse:
        data = await self.service.get_recent_news(session, request)
        return self._response(data)

    async def get_company_news(self, session: AsyncSession, request: CompanyNewsRequest) -> ToolResponse:
        data = await self.service.get_company_news(session, request)
        return self._response(data)

    @staticmethod
    def _response(data, *, warnings: list[str] | None = None) -> ToolResponse:
        status = {
            "available": ToolStatus.OK,
            "no_relevant_news": ToolStatus.NOT_FOUND,
            "partial": ToolStatus.PARTIAL,
            "stale": ToolStatus.PARTIAL,
            "unavailable": ToolStatus.UNAVAILABLE,
        }.get(data.coverage_status, ToolStatus.OK if data.articles else ToolStatus.NOT_FOUND)
        return ToolResponse(
            status=status,
            data=data,
            warnings=warnings or [],
            trace_id=uuid4(),
            generated_at=datetime.now(timezone.utc),
        )
