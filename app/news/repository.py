import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.news.models import NewsArticle, NewsSource


def _clean_body(body: str) -> str:
    """Normalize whitespace while keeping paragraphs readable."""
    lines = [re.sub(r"\s+", " ", line).strip() for line in body.splitlines()]
    return "\n".join(line for line in lines if line)


async def save_article(session: AsyncSession, article: dict[str, Any]) -> None:
    source_result = await session.execute(
        select(NewsSource).where(NewsSource.source_key == article["source_key"])
    )
    source = source_result.scalar_one_or_none()

    if source is None:
        raise ValueError(f"News source not found: {article['source_key']}")

    published_at = article.get("published_at")
    if published_at:
        published_at = datetime.fromisoformat(published_at.replace("Z", "+00:00"))

    body_original = article["body"]

    statement = (
        insert(NewsArticle)
        .values(
            source_id=source.id,
            external_article_id=article["external_article_id"],
            source_url=article["source_url"],
            canonical_url=article["source_url"],
            title_original=article["title"],
            title_normalized=article["title"].strip(),
            body_original=body_original,
            body_cleaned=_clean_body(body_original),
            body_excerpt=_clean_body(body_original)[:1000],
            language="en",
            published_at=published_at,
            content_rights="full_text",
            processing_status="pending",
        )
        .on_conflict_do_update(
            constraint="uq_article_source_external_id",
            set_={
                "source_url": article["source_url"],
                "canonical_url": article["source_url"],
                "title_original": article["title"],
                "title_normalized": article["title"].strip(),
                "body_original": body_original,
                "body_cleaned": _clean_body(body_original),
                "body_excerpt": _clean_body(body_original)[:1000],
                "published_at": published_at,
                "content_rights": "full_text",
            },
        )
    )

    await session.execute(statement)
    await session.commit()
    
async def article_exists(
    session: AsyncSession,
    source_key: str,
    external_article_id: str,
) -> bool:
    result = await session.execute(
        select(NewsArticle.id)
        .join(NewsSource, NewsArticle.source_id == NewsSource.id)
        .where(
            NewsSource.source_key == source_key,
            NewsArticle.external_article_id == external_article_id,
        )
        .limit(1)
    )
    return result.scalar_one_or_none() is not None