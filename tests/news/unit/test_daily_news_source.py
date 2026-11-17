from app.companies.catalog import EGX_COMPANIES
from app.news.sources.daily_news import DailyNewsSource


def test_daily_news_source_covers_all_seeded_egx_companies():
    source = DailyNewsSource()
    assert source.source_key == "daily_news_egypt"
    assert source.content_policy == "full_text"
    assert source.tickers == tuple(EGX_COMPANIES)


def test_daily_news_source_uses_listing_ticker_metadata():
    source = DailyNewsSource(tickers=("COMI",), per_ticker=1)
    assert source.tickers == ("COMI",)
    assert source.per_ticker == 1
