from datetime import datetime
from typing import Optional
from uuid import UUID, uuid4

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import UUID as PGUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.core.base import Base


class NewsSource(Base):
    __tablename__ = "news_sources"

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_key: Mapped[str] = mapped_column(String(100), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    source_type: Mapped[str] = mapped_column(String(50), default="official_disclosure", nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    content_policy: Mapped[str] = mapped_column(String(30), default="metadata_only", nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class NewsArticle(Base):
    __tablename__ = "news_articles"
    __table_args__ = (
        UniqueConstraint("source_id", "external_article_id", name="uq_article_source_external_id"),
        Index("ix_news_articles_published_at", "published_at"),
    )

    id: Mapped[UUID] = mapped_column(PGUUID(as_uuid=True), primary_key=True, default=uuid4)
    source_id: Mapped[UUID] = mapped_column(
        PGUUID(as_uuid=True), ForeignKey("news_sources.id"), nullable=False
    )
    external_article_id: Mapped[Optional[str]] = mapped_column(String(200))
    source_url: Mapped[str] = mapped_column(String(2000), nullable=False)
    canonical_url: Mapped[Optional[str]] = mapped_column(String(2000))
    title_original: Mapped[str] = mapped_column(Text, nullable=False)
    title_normalized: Mapped[str] = mapped_column(Text, nullable=False)
    body_cleaned: Mapped[Optional[str]] = mapped_column(Text)
    body_original: Mapped[Optional[str]] = mapped_column(Text)
    body_excerpt: Mapped[Optional[str]] = mapped_column(Text)
    language: Mapped[str] = mapped_column(String(10), default="unknown", nullable=False)
    published_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True))
    retrieved_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    content_rights: Mapped[str] = mapped_column(String(30), default="metadata_only", nullable=False)
    processing_status: Mapped[str] = mapped_column(String(30), default="pending", nullable=False)