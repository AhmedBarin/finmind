from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4
from typing import Any, Optional
from app.companies.models import Company as _Company  # Registers the company FK target
from sqlalchemy import text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy import (
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base


class NewsSource(Base):
    __tablename__ = "news_sources"

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    source_key: Mapped[str] = mapped_column(
        String(100),
        unique=True,
        nullable=False,
    )
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(
        String(50),
        default="official_disclosure",
        nullable=False,
    )
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    enabled: Mapped[bool] = mapped_column(
        Boolean,
        default=True,
        nullable=False,
    )
    content_policy: Mapped[str] = mapped_column(
        String(30),
        default="metadata_only",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )


class NewsArticle(Base):
    __tablename__ = "news_articles"
    __table_args__ = (
        UniqueConstraint(
            "source_id",
            "external_article_id",
            name="uq_article_source_external_id",
        ),
        Index("ix_news_articles_published_at", "published_at"),
        Index("ix_news_articles_content_hash", "content_hash"),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("news_sources.id"),
        nullable=False,
    )
    external_article_id: Mapped[Optional[str]] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    canonical_url: Mapped[Optional[str]] = mapped_column(String(2000))
    title_original: Mapped[str] = mapped_column(Text, nullable=False)
    title_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    body_excerpt: Mapped[Optional[str]] = mapped_column(Text)
    language: Mapped[str] = mapped_column(
        String(10),
        default="unknown",
        nullable=False,
    )
    published_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    content_rights: Mapped[str] = mapped_column(
        String(30),
        default="metadata_only",
        nullable=False,
    )
    processing_status: Mapped[str] = mapped_column(
        String(30),
        default="pending",
        nullable=False,
    )
    body_original: Mapped[Optional[str]] = mapped_column(Text)
    body_cleaned: Mapped[Optional[str]] = mapped_column(Text)

    author: Mapped[Optional[str]] = mapped_column(String(300))
    updated_at_source: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    raw_metadata: Mapped[dict[str, Any]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    content_hash: Mapped[Optional[str]] = mapped_column(String(64))
    pipeline_version: Mapped[str] = mapped_column(
        String(50),
        default="news-v1",
        server_default="news-v1",
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

class NewsIngestionRun(Base):
    __tablename__ = "ingestion_runs"
    __table_args__ = (
        CheckConstraint(
            "status IN ('running', 'success', 'partial', 'failed')",
            name="ck_ingestion_runs_status",
        ),
        CheckConstraint(
            "items_seen >= 0 AND items_new >= 0 "
            "AND items_duplicate >= 0 AND items_failed >= 0",
            name="ck_ingestion_runs_nonnegative_counts",
        ),
        Index(
            "ix_ingestion_runs_source_started_at",
            "source_id",
            "started_at",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("news_sources.id"),
        nullable=False,
    )
    started_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    finished_at: Mapped[Optional[datetime]] = mapped_column(
        DateTime(timezone=True)
    )
    status: Mapped[str] = mapped_column(
        String(20),
        default="running",
        nullable=False,
    )
    items_seen: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    items_new: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    items_duplicate: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    items_failed: Mapped[int] = mapped_column(
        Integer,
        default=0,
        nullable=False,
    )
    error_code: Mapped[Optional[str]] = mapped_column(String(100))
    error_summary: Mapped[Optional[str]] = mapped_column(Text)
    cursor_before: Mapped[Optional[str]] = mapped_column(Text)
    cursor_after: Mapped[Optional[str]] = mapped_column(Text)
    run_config_version: Mapped[str] = mapped_column(
        String(50),
        default="v1",
        nullable=False,
    )

class ArticleCompanyLink(Base):
    """Links one article to a company, preserving match status and evidence."""

    __tablename__ = "article_company_links"
    __table_args__ = (
        UniqueConstraint(
            "article_id",
            "company_id",
            name="uq_article_company_links_article_company",
        ),
        Index(
            "ix_article_company_links_company_status",
            "company_id",
            "link_status",
        ),
        CheckConstraint(
            "link_method IN "
            "('exact_alias', 'ticker_match', 'model_assisted', 'manual', 'other')",
            name="ck_article_company_links_method",
        ),
        CheckConstraint(
            "link_status IN ('confirmed', 'candidate', 'ambiguous', 'rejected')",
            name="ck_article_company_links_status",
        ),
        CheckConstraint(
            "relevance_score IS NULL OR "
            "(relevance_score >= 0 AND relevance_score <= 1)",
            name="ck_article_company_links_relevance_range",
        ),
        CheckConstraint(
            "link_confidence IS NULL OR "
            "(link_confidence >= 0 AND link_confidence <= 1)",
            name="ck_article_company_links_confidence_range",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    article_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("news_articles.id", ondelete="CASCADE"),
        nullable=False,
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    ticker_at_analysis: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    relevance_score: Mapped[Optional[float]] = mapped_column(Float)
    link_confidence: Mapped[Optional[float]] = mapped_column(Float)
    link_method: Mapped[str] = mapped_column(
        String(30),
        nullable=False,
    )
    link_status: Mapped[str] = mapped_column(
        String(20),
        nullable=False,
    )
    evidence_spans: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )