from uuid import uuid4
from datetime import datetime, timezone

from app.news.schemas import FetchedArticle
from app.news.sources.daily_news_preview import DailyNewsPreviewSource


def article(title: str, body: str) -> FetchedArticle:
    return FetchedArticle(
        external_article_id=None,
        source_url="https://dailynewsegypt.com/example",
        title_original=title,
        body_original=body,
        language="en",
    )


def test_daily_news_preview_uses_title_or_repeated_body_match():
    assert DailyNewsPreviewSource.matches_ticker(article("CIB reports growth", "unrelated"), "COMI")
    assert DailyNewsPreviewSource.matches_ticker(article("Market update", "CIB and CIB results"), "COMI")
    assert not DailyNewsPreviewSource.matches_ticker(article("Market update", "CIB mentioned once"), "COMI")


def test_preview_extraction_keeps_source_url_and_body():
    html = """
    <html><head><meta property='og:title' content='CIB results improve'/>
    <meta property='article:published_time' content='2026-11-15T10:00:00+02:00'/></head>
    <body><article><p>CIB reported strong results and CIB expanded lending. The bank said revenue and profitability improved during the reporting period with stronger deposits and customer lending growth.</p></article></body></html>
    """
    result = DailyNewsPreviewSource.extract_article(html, "https://dailynewsegypt.com/example")
    assert result is not None
    assert result.title_original == "CIB results improve"
    assert "strong results" in (result.body_original or "")
    assert result.published_at is not None


def test_url_date_is_used_when_page_metadata_is_missing():
    result = article("CIB results", "CIB reported results and CIB expanded lending")
    published_at, source = DailyNewsPreviewSource.resolve_published_at(
        article=result,
        api_date=None,
        url="https://dailynewsegypt.com/2024/05/09/cib-results/",
        now=datetime(2026, 11, 21, tzinfo=timezone.utc),
    )
    assert published_at == datetime(2024, 5, 8, 22, tzinfo=timezone.utc)
    assert source == "url"


def test_wordpress_date_is_used_when_url_date_is_unavailable():
    result = article("CIB results", "CIB reported results and CIB expanded lending")
    published_at, source = DailyNewsPreviewSource.resolve_published_at(
        article=result,
        api_date="2026-11-10T12:00:00Z",
        url="https://dailynewsegypt.com/cib-results/",
        now=datetime(2026, 11, 21, tzinfo=timezone.utc),
    )
    assert published_at == datetime(2026, 11, 10, 12, tzinfo=timezone.utc)
    assert source == "wordpress_api"


def test_url_date_wins_when_page_metadata_is_inconsistent():
    result = article("CIB results", "CIB reported results and CIB expanded lending").model_copy(
        update={"published_at": datetime(2026, 11, 20, 12, 49, tzinfo=timezone.utc)}
    )
    published_at, source = DailyNewsPreviewSource.resolve_published_at(
        article=result,
        api_date="2026-11-20T12:49:11Z",
        url="https://dailynewsegypt.com/2026/11/10/cib-results/",
        now=datetime(2026, 11, 21, tzinfo=timezone.utc),
    )
    assert published_at == datetime(2026, 11, 9, 22, tzinfo=timezone.utc)
    assert source == "url"


def test_page_metadata_is_preferred_and_future_dates_are_rejected():
    result = article("CIB results", "CIB reported results and CIB expanded lending").model_copy(
        update={"published_at": datetime(2026, 11, 15, 10, tzinfo=timezone.utc)}
    )
    published_at, source = DailyNewsPreviewSource.resolve_published_at(
        article=result,
        api_date="2026-11-20T12:00:00Z",
        url="https://dailynewsegypt.com/cib-results/",
        now=datetime(2026, 11, 21, tzinfo=timezone.utc),
    )
    assert published_at == datetime(2026, 11, 15, 10, tzinfo=timezone.utc)
    assert source == "page_metadata"

    future = result.model_copy(update={"published_at": datetime(2027, 1, 1, tzinfo=timezone.utc)})
    published_at, source = DailyNewsPreviewSource.resolve_published_at(
        article=future,
        api_date=None,
        url="https://dailynewsegypt.com/cib-results/",
        now=datetime(2026, 11, 21, tzinfo=timezone.utc),
    )
    assert published_at is None
    assert source == "future_date"
