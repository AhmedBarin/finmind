"""Bounded, read-only evidence and similar-news tools."""

from datetime import datetime, timezone
from uuid import UUID, uuid4

from app.agents.news_agent.retrieval_schemas import (
    AnnualReportEvidenceRequest,
    EvidenceItem,
    RetrievalData,
    RetrievalToolResponse,
    SimilarNewsItem,
    SimilarNewsRequest,
)
from app.agents.news_agent.schemas import ToolStatus


class NewsRetrievalTools:
    def __init__(self, index) -> None:
        self.index = index

    def get_annual_report_evidence(self, request: AnnualReportEvidenceRequest) -> RetrievalToolResponse:
        try:
            matches = self.index.query(request.query, limit=request.limit * 5)
        except Exception as exc:
            return self._response("unavailable", [], ["Vector store is unavailable."], str(exc)[:300])
        items = []
        for chunk, score in matches:
            metadata = chunk.metadata
            if not self._matches_company(metadata, request.ticker, request.company_id):
                continue
            if metadata.get("document_type") not in {"annual_report", "annual_financial_report"}:
                continue
            if request.fiscal_year is not None and metadata.get("fiscal_year") != request.fiscal_year:
                continue
            if not self._matches_date(metadata, request.start_at, request.end_at):
                continue
            items.append(EvidenceItem(
                chunk_id=chunk.chunk_id, article_id=chunk.article_id,
                evidence_text=chunk.text, source_url=metadata.get("source_url"),
                source_name=metadata.get("source_name"), document_title=metadata.get("document_title"),
                document_type=metadata.get("document_type"), publication_date=self._date(metadata.get("published_at")),
                fiscal_year=metadata.get("fiscal_year"), page=metadata.get("page"),
                section=metadata.get("section"), retrieval_score=float(score),
            ))
            if len(items) >= request.limit:
                break
        status = "ok" if items else "not_found"
        return self._response(status, items, [] if items else ["No permitted annual report evidence was indexed."])

    def retrieve_similar_news(self, request: SimilarNewsRequest) -> RetrievalToolResponse:
        query = request.query
        if not query and request.article_id is not None:
            article_chunks = getattr(self.index, "article_chunks", None)
            if article_chunks is None:
                return self._response("unavailable", [], ["The configured index cannot load an article by ID."])
            chunks = article_chunks(request.article_id)
            if not chunks:
                return self._response("not_found", [], ["Source article is not indexed."])
            query = " ".join(chunk.text for chunk in chunks[:3])
        try:
            matches = self.index.query(query or "", limit=request.limit * 5)
        except Exception as exc:
            return self._response("unavailable", [], ["Vector store is unavailable."], str(exc)[:300])
        items = []
        seen: set[UUID] = set()
        for chunk, score in matches:
            if request.article_id == chunk.article_id:
                continue
            metadata = chunk.metadata
            if chunk.article_id in seen or not self._matches_company(metadata, request.ticker, request.company_id):
                continue
            if request.event_types and metadata.get("event_type") not in request.event_types:
                continue
            if not self._matches_date(metadata, request.start_at, request.end_at):
                continue
            seen.add(chunk.article_id)
            items.append(SimilarNewsItem(
                article_id=chunk.article_id, source_url=metadata.get("source_url"),
                source_name=metadata.get("source_name"), published_at=self._date(metadata.get("published_at")),
                event_type=metadata.get("event_type"), similarity_score=float(score), evidence_text=chunk.text,
            ))
            if len(items) >= request.limit:
                break
        return self._response("ok" if items else "not_found", items, ["Similarity is not a probability and does not predict future returns."])

    @staticmethod
    def _matches_company(metadata, ticker: str | None, company_id: UUID | None) -> bool:
        if ticker and ticker not in metadata.get("ticker_links", []):
            return False
        if company_id and str(company_id) not in metadata.get("company_ids", []):
            return False
        return True

    @staticmethod
    def _matches_date(metadata, start_at, end_at) -> bool:
        value = NewsRetrievalTools._date(metadata.get("published_at"))
        return not value or ((not start_at or value >= start_at) and (not end_at or value <= end_at))

    @staticmethod
    def _date(value):
        if not value:
            return None
        return datetime.fromisoformat(value) if isinstance(value, str) else value

    @staticmethod
    def _response(status, items, warnings, error=None):
        return RetrievalToolResponse(
            status=ToolStatus(status),
            data=RetrievalData(items=items, coverage_status=status, limitations=warnings),
            warnings=warnings, errors=[error] if error else [], trace_id=uuid4(), generated_at=datetime.now(timezone.utc),
        )
