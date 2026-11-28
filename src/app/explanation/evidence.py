"""Authorized, deterministic evidence retrieval for explanations."""

from __future__ import annotations

from collections.abc import Iterable

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


def _filter_items(
    items: Iterable[EvidenceItem], query: EvidenceQuery
) -> list[EvidenceItem]:
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


class NewsEvidenceRetriever:
    """Defensive adapter around an authorized News evidence backend."""

    def __init__(self, backend: EvidenceRetriever) -> None:
        self.backend = backend

    async def retrieve(self, query: EvidenceQuery) -> EvidenceResult:
        try:
            result = await self.backend.retrieve(query)
        except Exception:  # noqa: BLE001
            return EvidenceResult(
                status=DataAvailability.UNAVAILABLE,
                limitations=["News evidence retrieval is unavailable."],
            )

        items = _filter_items(result.items, query)
        status = result.status
        if status is DataAvailability.AVAILABLE and not items:
            status = DataAvailability.NOT_FOUND
        return result.model_copy(update={"status": status, "items": items})
