"""Daily News Egypt source adapter for scheduled FinMind ingestion."""

from __future__ import annotations

import os

from app.companies.catalog import EGX_COMPANIES
from app.news.sources.daily_news_preview import DailyNewsPreviewSource


class DailyNewsSource(DailyNewsPreviewSource):
    source_key = "daily_news_egypt"
    name = "Daily News Egypt"
    base_url = "https://www.dailynewsegypt.com"
    source_type = "news_provider"
    content_policy = "full_text"

    def __init__(
        self,
        *,
        timeout_seconds: float = 25,
        tickers: tuple[str, ...] | None = None,
        per_ticker: int | None = None,
    ) -> None:
        super().__init__(
            timeout_seconds=timeout_seconds,
            tickers=tickers or tuple(EGX_COMPANIES),
            per_ticker=per_ticker or int(os.getenv("DAILY_NEWS_ARTICLES_PER_TICKER", "3")),
        )
