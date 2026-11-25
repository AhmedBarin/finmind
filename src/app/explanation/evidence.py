"""Authorized, deterministic evidence retrieval for explanations."""

from __future__ import annotations

import asyncio
from collections.abc import Iterable
from datetime import UTC, datetime, time

from app.agents.news_agent.retrieval_schemas import SimilarNewsItem as NewsSimilarNewsItem
from app.agents.news_agent.retrieval_schemas import SimilarNewsRequest
from app.agents.news_agent.schemas import ToolStatus
from app.explanation.interfaces import EvidenceRetriever
from app.explanation.schemas import (
    DataAvailability,
    EvidenceItem,
    EvidenceQuery,
    EvidenceResult,
)


def build_evidence_query(
    *,
    ticker: str | None = None,
    as_of=None,
    query_text: str = "",
    reasons: list[str] | None = None,
    alert_type: str | None = None,
    limit: int = 10,
) -> EvidenceQuery:
    return EvidenceQuery(
        ticker=ticker,
        as_of=as_of,
        query_text=query_text,
        reasons=reasons or [],
        alert_type=alert_type,
        limit=limit,
    )


def _deduplicate(items: Iterable[EvidenceItem]) -> list[EvidenceItem]:
    seen: set[str] = set()
    result: list[EvidenceItem] = []
    for item in items:
        if item.evidence_id in seen:
            continue
        seen.add(item.evidence_id)
        result.append(item)
    return result


def _filter_items(items: Iterable[EvidenceItem], query: EvidenceQuery) -> list[EvidenceItem]:
    filtered: list[EvidenceItem] = []
    for item in _deduplicate(items):
        if query.ticker and item.ticker != query.ticker:
            continue
        if query.as_of and item.published_at and item.published_at.date() > query.as_of:
            continue
        filtered.append(item)
        if len(filtered) >= query.limit:
            break
    return filtered


class NewsToolsEvidenceBackend:
    """Adapt the existing authorized News Agent retriever to Explanation evidence."""

    def __init__(self, tools: object) -> None:
        self.tools = tools

    async def retrieve(self, query: EvidenceQuery) -> EvidenceResult:
        retrieve = getattr(self.tools, "retrieve_similar_news", None)
        if retrieve is None:
            return EvidenceResult(
                status=DataAvailability.UNAVAILABLE,
                limitations=["News evidence retrieval is not configured."],
            )

        query_text = query.query_text.strip() or " ".join(
            [query.ticker or "EGX stock", *query.reasons, query.alert_type or ""]
        )
        end_at = (
            datetime.combine(query.as_of, time.max, tzinfo=UTC)
            if query.as_of is not None
            else None
        )
        request = SimilarNewsRequest(
            query=query_text[:500],
            ticker=query.ticker,
            end_at=end_at,
            limit=min(query.limit, 10),
        )
        try:
            response = await asyncio.to_thread(retrieve, request)
        except Exception:
            return EvidenceResult(
                status=DataAvailability.UNAVAILABLE,
                limitations=["News evidence retrieval is unavailable."],
            )

        status_map = {
            ToolStatus.OK: DataAvailability.AVAILABLE,
            ToolStatus.PARTIAL: DataAvailability.PARTIAL,
            ToolStatus.NOT_FOUND: DataAvailability.NOT_FOUND,
            ToolStatus.UNAVAILABLE: DataAvailability.UNAVAILABLE,
            ToolStatus.FAILED: DataAvailability.UNAVAILABLE,
            ToolStatus.INVALID_REQUEST: DataAvailability.PARTIAL,
        }
        mapped_items: list[EvidenceItem] = []
        for item in response.data.items:
            if not isinstance(item, NewsSimilarNewsItem):
                continue
            title = item.event_type or item.source_name or "Related company news"
            mapped_items.append(
                EvidenceItem(
                    evidence_id=str(item.article_id),
                    article_id=item.article_id,
                    source_name=item.source_name,
                    title=title[:1000],
                    source_url=item.source_url,
                    published_at=item.published_at,
                    excerpt=item.evidence_text,
                    ticker=query.ticker,
                )
            )
        limitations = list(response.data.limitations) + list(response.warnings)
        if response.status in {ToolStatus.FAILED, ToolStatus.INVALID_REQUEST}:
            limitations.extend(response.errors)
        return EvidenceResult(
            status=status_map[response.status],
            items=mapped_items,
            limitations=list(dict.fromkeys(limitations))[:20],
        )


class NewsEvidenceRetriever:
    """Defensive adapter around an authorized News evidence backend."""

    def __init__(self, backend: EvidenceRetriever) -> None:
        self.backend = backend

    async def retrieve(self, query: EvidenceQuery) -> EvidenceResult:
        try:
            result = await self.backend.retrieve(query)
        except Exception:
            return EvidenceResult(
                status=DataAvailability.UNAVAILABLE,
                limitations=["News evidence retrieval is unavailable."],
            )

        items = _filter_items(result.items, query)
        status = result.status
        limitations = list(result.limitations)
        if status is DataAvailability.AVAILABLE and not items:
            status = DataAvailability.NOT_FOUND
        if status is DataAvailability.NOT_FOUND and not limitations:
            limitations.append("No relevant news evidence was found for this request.")
        return result.model_copy(
            update={"status": status, "items": items, "limitations": limitations[:20]}
        )
