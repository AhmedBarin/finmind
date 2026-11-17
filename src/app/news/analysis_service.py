"""Coordinates permitted article context, LLM analysis, validation, and storage."""

from hashlib import sha256
from typing import Any, Protocol
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.companies.models import Company
from app.news.analysis_prompt import PIPELINE_VERSION, PROMPT_VERSION, TAXONOMY_VERSION
from app.news.analysis_repository import NewsAnalysisRepository
from app.news.analysis_schemas import (
    NewsDirection,
    StructuredNewsAnalysis,
)
from app.news.groq_client import GroqAnalysisClient
from app.news.models import ArticleCompanyLink, NewsArticle, NewsAnalysis


class NewsAnalysisModel(Protocol):
    model_name: str

    async def analyze(
        self,
        *,
        article_fields: dict[str, str],
        language: str,
        company_context: dict[str, Any] | None,
        published_at: str | None,
    ) -> StructuredNewsAnalysis: ...


class NewsAnalysisService:
    def __init__(
        self,
        *,
        model_client: NewsAnalysisModel | None = None,
        repository: NewsAnalysisRepository | None = None,
    ) -> None:
        self.model_client = model_client or GroqAnalysisClient.from_settings()
        self.repository = repository or NewsAnalysisRepository()

    async def analyze_article(
        self,
        session: AsyncSession,
        *,
        article_id: UUID,
        company_id: UUID | None = None,
    ) -> NewsAnalysis:
        article = await session.get(NewsArticle, article_id)
        if article is None:
            raise LookupError(f"News article not found: {article_id}")

        company_context: dict[str, Any] | None = None
        link: ArticleCompanyLink | None = None
        if company_id is not None:
            link = await session.scalar(
                select(ArticleCompanyLink).where(
                    ArticleCompanyLink.article_id == article_id,
                    ArticleCompanyLink.company_id == company_id,
                )
            )
            if link is None or link.link_status == "rejected":
                raise ValueError(
                    "Article does not have an analyzable link to this company"
                )

            company = await session.get(Company, company_id)
            if company is None:
                raise LookupError(f"Company not found: {company_id}")
            company_context = {
                "company_id": str(company.id),
                "ticker": company.ticker,
                "name_ar": company.name_ar,
                "name_en": company.name_en,
                "link_status": link.link_status,
                "link_confidence": link.link_confidence,
            }

        article_fields = self._permitted_article_fields(article)
        result = await self.model_client.analyze(
            article_fields=article_fields,
            language=article.language,
            company_context=company_context,
            published_at=(
                article.published_at.isoformat() if article.published_at else None
            ),
        )

        if company_context is None:
            result = self._require_review(
                result,
                "No company was linked; company-specific classification was not assigned.",
            )
        elif link is not None and link.link_status != "confirmed":
            result = self._require_review(
                result,
                "The company link is not confirmed; classification requires human review.",
            )

        model_name = self.model_client.model_name
        analysis_version = self._analysis_version(model_name)
        return await self.repository.save_analysis(
            session,
            article_id=article_id,
            company_id=company_id,
            analysis=result,
            analysis_version=analysis_version,
            prompt_version=PROMPT_VERSION,
            taxonomy_version=TAXONOMY_VERSION,
            pipeline_version=PIPELINE_VERSION,
            model_provider="groq",
            model_name=model_name,
        )

    @staticmethod
    def _permitted_article_fields(article: NewsArticle) -> dict[str, str]:
        fields = {"title_original": article.title_original}
        policy = article.content_rights.casefold()

        if policy in {"full_text", "full_text_permitted"}:
            if article.body_cleaned:
                fields["body_cleaned"] = article.body_cleaned
            elif article.body_original:
                fields["body_original"] = article.body_original
        elif policy == "excerpt" and article.body_excerpt:
            fields["body_excerpt"] = article.body_excerpt

        return fields

    @staticmethod
    def _require_review(
        result: StructuredNewsAnalysis,
        limitation: str,
    ) -> StructuredNewsAnalysis:
        limitations = list(result.limitations)
        if limitation not in limitations:
            limitations.append(limitation)
        return result.model_copy(
            update={
                "direction": NewsDirection.UNKNOWN,
                "requires_human_review": True,
                "limitations": limitations,
            }
        )

    @staticmethod
    def _analysis_version(model_name: str) -> str:
        version_input = "|".join(
            ("groq", model_name, PROMPT_VERSION, TAXONOMY_VERSION, PIPELINE_VERSION)
        )
        suffix = sha256(version_input.encode("utf-8")).hexdigest()[:20]
        return f"news-analysis-{suffix}"
