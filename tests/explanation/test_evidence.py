from datetime import datetime, timezone
from uuid import uuid4

import pytest

from app.explanation.evidence import NewsEvidenceRetriever, build_evidence_query
from app.explanation.schemas import DataAvailability, EvidenceItem, EvidenceResult


class Backend:
    async def retrieve(self, query):
        return EvidenceResult(
            status=DataAvailability.AVAILABLE,
            items=[
                EvidenceItem(evidence_id="1", title="COMI", ticker="COMI"),
                EvidenceItem(evidence_id="1", title="duplicate", ticker="COMI"),
                EvidenceItem(evidence_id="2", title="SWDY", ticker="SWDY"),
            ],
        )


class BrokenBackend:
    async def retrieve(self, query):
        raise RuntimeError("database unavailable")


@pytest.mark.asyncio
async def test_retriever_filters_ticker_and_deduplicates() -> None:
    query = build_evidence_query(ticker="comi", limit=10)

    result = await NewsEvidenceRetriever(Backend()).retrieve(query)

    assert result.status is DataAvailability.AVAILABLE
    assert [item.evidence_id for item in result.items] == ["1"]


@pytest.mark.asyncio
async def test_retriever_reports_backend_failure_without_leaking_exception() -> None:
    result = await NewsEvidenceRetriever(BrokenBackend()).retrieve(
        build_evidence_query(ticker="COMI")
    )

    assert result.status is DataAvailability.UNAVAILABLE
    assert result.items == []
    assert result.limitations == ["News evidence retrieval is unavailable."]


def test_query_limit_is_bounded_by_contract() -> None:
    with pytest.raises(ValueError):
        build_evidence_query(limit=0)

