"""Agent-facing wrapper around the existing validated LLM analysis service."""

from datetime import datetime, timezone
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.news.analysis_service import NewsAnalysisService
from app.news.analysis_schemas import StructuredNewsAnalysis
from app.news.groq_client import GroqAnalysisError
from app.news.schemas import NewsAnalysisRead
from app.agents.news_agent.analysis_schemas import (
    StructuredAnalysisData,
    StructuredAnalysisItem,
    StructuredAnalysisRequest,
    StructuredAnalysisResponse,
)


class NewsAnalysisTools:
    def __init__(self, service: NewsAnalysisService) -> None:
        self.service = service

    async def structured_news_analysis(
        self,
        session: AsyncSession,
        request: StructuredAnalysisRequest,
    ) -> StructuredAnalysisResponse:
        items: list[StructuredAnalysisItem] = []
        limitations: list[str] = []
        succeeded = 0
        if request.permitted_text is not None:
            try:
                result = await self.service.model_client.analyze(
                    article_fields={"permitted_text": request.permitted_text},
                    language="unknown", company_context=None, published_at=None,
                )
                items.append(StructuredAnalysisItem(article_id=None, status="ok", analysis=result))
                succeeded = 1
            except (ValueError, GroqAnalysisError) as exc:
                items.append(StructuredAnalysisItem(article_id=None, status="failed", error=str(exc)))
        for article_id in request.article_ids:
            try:
                result = await self.service.analyze_article(
                    session, article_id=article_id, company_id=request.company_id
                )
                items.append(StructuredAnalysisItem(
                    article_id=article_id,
                    status="ok",
                    analysis=NewsAnalysisRead.model_validate(result),
                ))
                succeeded += 1
            except LookupError as exc:
                items.append(StructuredAnalysisItem(article_id=article_id, status="not_found", error=str(exc)))
            except ValueError as exc:
                items.append(StructuredAnalysisItem(article_id=article_id, status="invalid_request", error=str(exc)))
            except GroqAnalysisError as exc:
                items.append(StructuredAnalysisItem(article_id=article_id, status="unavailable", error=str(exc)))

        if request.task_mode != "classify":
            limitations.append(
                "The current persisted contract returns one validated evidence-backed analysis; "
                f"task mode '{request.task_mode.value}' does not change the classification schema."
            )
        if succeeded:
            await session.commit()
        statuses = {item.status for item in items}
        overall = "ok" if succeeded == len(items) else "partial" if succeeded else "failed"
        return StructuredAnalysisResponse(
            status=overall,
            data=StructuredAnalysisData(task_mode=request.task_mode, items=items, limitations=limitations),
            warnings=limitations,
            errors=[item.error for item in items if item.error],
            trace_id=uuid4(),
            generated_at=datetime.now(timezone.utc).isoformat(),
        )
