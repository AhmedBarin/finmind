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


class NewsAnalysis(Base):
    """Versioned, evidence-backed analysis for an article and optional company."""

    __tablename__ = "news_analyses"
    __table_args__ = (
        CheckConstraint(
            "direction IN ('positive', 'negative', 'neutral', 'unknown')",
            name="ck_news_analyses_direction",
        ),
        CheckConstraint(
            "source_reliability IS NULL OR "
            "(source_reliability >= 0 AND source_reliability <= 1)",
            name="ck_news_analyses_source_reliability_range",
        ),
        CheckConstraint(
            "review_status IN ('not_required', 'pending', 'approved', 'rejected', 'corrected')",
            name="ck_news_analyses_review_status",
        ),
        CheckConstraint(
            "event_type IN ("
            "'earnings_results', 'revenue_or_profit_change', "
            "'dividend_announcement', 'capital_increase_or_rights_issue', "
            "'merger_acquisition_or_disposal', 'management_or_board_change', "
            "'regulatory_or_legal', 'trading_suspension_or_resumption', "
            "'material_contract_or_order', 'debt_or_financing', "
            "'ownership_or_major_shareholder', 'macroeconomic_or_sector', "
            "'analyst_opinion_or_forecast', 'rumor_or_unverified_claim', "
            "'routine_corporate_update', 'other', 'unknown')",
            name="ck_news_analyses_event_type",
        ),
        CheckConstraint(
            "relevance_score >= 0 AND relevance_score <= 1",
            name="ck_news_analyses_relevance_range",
        ),
        CheckConstraint(
            "novelty_score >= 0 AND novelty_score <= 1",
            name="ck_news_analyses_novelty_range",
        ),
        Index(
            "ix_news_analyses_article_analyzed_at",
            "article_id",
            "analyzed_at",
        ),
        Index(
            "ix_news_analyses_company_analyzed_at",
            "company_id",
            "analyzed_at",
        ),
        Index(
            "uq_news_analyses_article_company_version",
            "article_id",
            "company_id",
            "analysis_version",
            unique=True,
            postgresql_where=text("company_id IS NOT NULL"),
        ),
        Index(
            "uq_news_analyses_article_only_version",
            "article_id",
            "analysis_version",
            unique=True,
            postgresql_where=text("company_id IS NULL"),
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
    company_id: Mapped[Optional[UUID]] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="SET NULL"),
    )
    analysis_version: Mapped[str] = mapped_column(String(50), nullable=False)
    schema_version: Mapped[str] = mapped_column(String(50), nullable=False)
    model_provider: Mapped[Optional[str]] = mapped_column(String(100))
    model_name: Mapped[Optional[str]] = mapped_column(String(200))
    prompt_version: Mapped[str] = mapped_column(String(50), nullable=False)
    taxonomy_version: Mapped[str] = mapped_column(String(50), nullable=False)
    pipeline_version: Mapped[str] = mapped_column(String(50), nullable=False)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    relevance_score: Mapped[float] = mapped_column(Float, nullable=False)
    novelty_score: Mapped[float] = mapped_column(Float, nullable=False)
    source_reliability: Mapped[Optional[float]] = mapped_column(Float)
    classification_confidence: Mapped[dict[str, float]] = mapped_column(
        JSONB,
        nullable=False,
    )
    summary_ar: Mapped[Optional[str]] = mapped_column(Text)
    summary_en: Mapped[Optional[str]] = mapped_column(Text)
    key_facts: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    contradictions: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    evidence_spans: Mapped[list[dict[str, Any]]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    requires_human_review: Mapped[bool] = mapped_column(
        Boolean,
        default=False,
        server_default=text("false"),
        nullable=False,
    )
    review_status: Mapped[str] = mapped_column(
        String(20),
        default="pending",
        server_default="pending",
        nullable=False,
    )
    limitations: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    analyzed_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
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


class NewsSignal(Base):
    """Versioned, deterministic company-level news signal for downstream use."""

    __tablename__ = "news_signals"
    __table_args__ = (
        UniqueConstraint(
            "company_id",
            "aggregation_config_version",
            "input_hash",
            name="uq_news_signals_company_config_input",
        ),
        CheckConstraint(
            "direction IN ('positive', 'negative', 'neutral', 'unknown')",
            name="ck_news_signals_direction",
        ),
        CheckConstraint(
            "coverage_status IN "
            "('available', 'no_relevant_news', 'stale', 'partial', 'unavailable')",
            name="ck_news_signals_coverage_status",
        ),
        CheckConstraint(
            "article_count >= 0 AND eligible_article_count >= 0",
            name="ck_news_signals_nonnegative_counts",
        ),
        CheckConstraint(
            "freshness_seconds IS NULL OR freshness_seconds >= 0",
            name="ck_news_signals_freshness_nonnegative",
        ),
        Index(
            "ix_news_signals_company_as_of",
            "company_id",
            "as_of",
        ),
    )

    id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        primary_key=True,
        default=uuid4,
    )
    company_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True),
        ForeignKey("companies.id", ondelete="CASCADE"),
        nullable=False,
    )
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    signal_version: Mapped[str] = mapped_column(String(50), nullable=False)
    aggregation_config_version: Mapped[str] = mapped_column(
        String(50), nullable=False
    )
    input_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    direction: Mapped[str] = mapped_column(String(20), nullable=False)
    article_count: Mapped[int] = mapped_column(Integer, nullable=False)
    eligible_article_count: Mapped[int] = mapped_column(Integer, nullable=False)
    coverage_status: Mapped[str] = mapped_column(String(30), nullable=False)
    freshness_seconds: Mapped[Optional[int]] = mapped_column(Integer)
    top_event_types: Mapped[dict[str, int]] = mapped_column(
        JSONB,
        default=dict,
        server_default=text("'{}'::jsonb"),
        nullable=False,
    )
    contributing_article_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    contributing_analysis_ids: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    reason_codes: Mapped[list[str]] = mapped_column(
        JSONB,
        default=list,
        server_default=text("'[]'::jsonb"),
        nullable=False,
    )
    limitations: Mapped[list[str]] = mapped_column(
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
