from uuid import uuid4

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
