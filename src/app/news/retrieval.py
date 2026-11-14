"""Permitted news chunking and vector-index integration.

PostgreSQL remains the canonical article store.  This module only prepares
evidence and sends it to an injected Chroma-compatible collection; it never
executes or interprets text found in an article.
"""

from __future__ import annotations

from dataclasses import dataclass
from hashlib import sha256
import re
from typing import Any, Protocol
from uuid import UUID


PERMITTED_POLICIES = frozenset({"full_text", "full_text_permitted", "excerpt"})
PIPELINE_VERSION = "news-retrieval-v1"


@dataclass(frozen=True)
class NewsChunk:
    chunk_id: str
    article_id: UUID
    text: str
    metadata: dict[str, Any]


@dataclass(frozen=True)
class IndexingResult:
    status: str
    article_id: UUID
    indexed_chunks: int = 0
    skipped_reason: str | None = None
    error: str | None = None


class VectorIndex(Protocol):
    def upsert(self, *, chunks: list[NewsChunk]) -> None: ...


class ChromaNewsVectorIndex:
    """Adapter for a configured Chroma collection.

    The collection is injected so importing the application does not require
    ChromaDB, and deployment can choose its own persistent client/configuration.
    """

    def __init__(self, collection: Any) -> None:
        self.collection = collection

    def upsert(self, *, chunks: list[NewsChunk]) -> None:
        if not chunks:
            return
        self.collection.upsert(
            ids=[chunk.chunk_id for chunk in chunks],
            documents=[chunk.text for chunk in chunks],
            metadatas=[chunk.metadata for chunk in chunks],
        )


class InMemoryNewsVectorIndex:
    """Deterministic test/development index with Chroma-like upsert semantics."""

    def __init__(self) -> None:
        self.chunks: dict[str, NewsChunk] = {}

    def upsert(self, *, chunks: list[NewsChunk]) -> None:
        for chunk in chunks:
            self.chunks[chunk.chunk_id] = chunk

    def query(self, text: str, *, limit: int = 5) -> list[NewsChunk]:
        terms = {term.casefold() for term in re.findall(r"\w+", text) if term}
        ranked = []
        for chunk in self.chunks.values():
            words = set(re.findall(r"\w+", chunk.text.casefold()))
            score = len(terms & words)
            if score:
                ranked.append((score, chunk))
        return [chunk for _, chunk in sorted(ranked, key=lambda item: (-item[0], item[1].chunk_id))[:limit]]


class NewsChunker:
    def __init__(self, *, max_chars: int = 1200, overlap_chars: int = 150) -> None:
        if max_chars < 100:
            raise ValueError("max_chars must be at least 100")
        if overlap_chars < 0 or overlap_chars >= max_chars:
            raise ValueError("overlap_chars must be between 0 and max_chars")
        self.max_chars = max_chars
        self.overlap_chars = overlap_chars

    def chunk_article(
        self,
        *,
        article: Any,
        source_name: str,
        ticker_links: list[str] | tuple[str, ...] = (),
    ) -> list[NewsChunk]:
        policy = str(article.content_rights or "").casefold()
        if policy not in PERMITTED_POLICIES:
            return []

        fields: list[tuple[str, str]] = [("title_original", article.title_original)]
        if policy in {"full_text", "full_text_permitted"}:
            body = article.body_cleaned or article.body_original
            if body:
                fields.append(("body_cleaned" if article.body_cleaned else "body_original", body))
        elif article.body_excerpt:
            fields.append(("body_excerpt", article.body_excerpt))

        chunks: list[NewsChunk] = []
        for source_field, text in fields:
            for local_index, piece in enumerate(self._split(text)):
                chunk_id = self._chunk_id(article.id, source_field, local_index, piece)
                metadata = {
                    "article_id": str(article.id),
                    "source_url": article.source_url,
                    "source_name": source_name,
                    "published_at": article.published_at.isoformat() if article.published_at else None,
                    "ticker_links": list(ticker_links),
                    "chunk_index": local_index,
                    "source_field": source_field,
                    "content_rights": policy,
                    "content_hash": article.content_hash,
                    "pipeline_version": PIPELINE_VERSION,
                }
                chunks.append(NewsChunk(chunk_id=chunk_id, article_id=article.id, text=piece, metadata=metadata))
        return chunks

    def _split(self, text: str) -> list[str]:
        normalized = re.sub(r"\s+", " ", text).strip()
        if not normalized:
            return []
        result: list[str] = []
        start = 0
        while start < len(normalized):
            end = min(start + self.max_chars, len(normalized))
            if end < len(normalized):
                boundary = normalized.rfind(" ", start, end)
                if boundary > start + self.max_chars // 2:
                    end = boundary
            piece = normalized[start:end].strip()
            if piece:
                result.append(piece)
            if end >= len(normalized):
                break
            next_start = max(end - self.overlap_chars, start + 1)
            start = next_start
        return result

    @staticmethod
    def _chunk_id(article_id: UUID, source_field: str, index: int, text: str) -> str:
        value = f"{article_id}|{PIPELINE_VERSION}|{source_field}|{index}|{text}"
        return sha256(value.encode("utf-8")).hexdigest()


class NewsRetrievalIndexer:
    def __init__(self, index: VectorIndex, *, chunker: NewsChunker | None = None) -> None:
        self.index = index
        self.chunker = chunker or NewsChunker()

    def index_article(
        self,
        *,
        article: Any,
        source_name: str,
        ticker_links: list[str] | tuple[str, ...] = (),
    ) -> IndexingResult:
        chunks = self.chunker.chunk_article(
            article=article, source_name=source_name, ticker_links=ticker_links
        )
        if not chunks:
            reason = "content_not_permitted" if article.content_rights not in PERMITTED_POLICIES else "empty_content"
            return IndexingResult(status="not_found", article_id=article.id, skipped_reason=reason)
        try:
            self.index.upsert(chunks=chunks)
        except Exception as exc:
            return IndexingResult(status="unavailable", article_id=article.id, error=str(exc)[:300])
        return IndexingResult(status="ok", article_id=article.id, indexed_chunks=len(chunks))

    def index_articles(
        self,
        *,
        articles: list[Any],
        source_name: str,
        ticker_links_by_article: dict[UUID, list[str] | tuple[str, ...]] | None = None,
    ) -> list[IndexingResult]:
        """Index a bounded batch while preserving per-article failure states."""
        results = []
        links = ticker_links_by_article or {}
        for article in articles:
            results.append(
                self.index_article(
                    article=article,
                    source_name=source_name,
                    ticker_links=links.get(article.id, ()),
                )
            )
        return results
