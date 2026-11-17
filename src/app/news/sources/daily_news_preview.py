"""Preview-only Daily News Egypt adapter.

This module deliberately does not register the source, persist articles, or
start scheduling. It is the verification step before full ingestion wiring.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
import os
import re
from urllib.parse import quote_plus, urljoin, urlparse

import httpx
from bs4 import BeautifulSoup

from app.companies.catalog import EGX_COMPANIES
from app.news.schemas import FetchedArticle
from app.news.sources.base import NewsSourceAdapter


SOURCE_KEY = "daily_news_egypt"
BASE_URL = "https://www.dailynewsegypt.com"
CAIRO = timezone(timedelta(hours=2))
MAX_AGE_DAYS = int(os.getenv("DAILY_NEWS_MAX_AGE_DAYS", "30"))
PER_TICKER = int(os.getenv("DAILY_NEWS_PREVIEW_PER_TICKER", "3"))
TICKERS = tuple(
    ticker.strip().upper()
    for ticker in os.getenv("DAILY_NEWS_PREVIEW_TICKERS", "COMI,SWDY,ETEL,TMGH").split(",")
    if ticker.strip()
)


class DailyNewsPreviewSource(NewsSourceAdapter):
    source_key = SOURCE_KEY
    name = "Daily News Egypt"
    base_url = BASE_URL
    source_type = "news_provider"
    content_policy = "full_text"

    def __init__(
        self,
        *,
        timeout_seconds: float = 25,
        tickers: tuple[str, ...] | None = None,
        per_ticker: int | None = None,
    ) -> None:
        self.timeout_seconds = timeout_seconds
        self.tickers = tickers or TICKERS
        self.per_ticker = per_ticker or PER_TICKER

    @staticmethod
    def clean_text(value: str | None) -> str:
        return re.sub(r"\s+", " ", value or "").strip()

    @classmethod
    def detect_language(cls, text: str) -> str:
        arabic = len(re.findall(r"[\u0600-\u06FF]", text))
        latin = len(re.findall(r"[A-Za-z]", text))
        if arabic and latin and min(arabic, latin) / max(arabic, latin) > 0.2:
            return "mixed"
        return "ar" if arabic > latin else "en"

    @classmethod
    def parse_date(cls, value: str | None) -> datetime | None:
        if not value:
            return None
        value = value.strip()
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=CAIRO)

    @classmethod
    def extract_date(cls, soup: BeautifulSoup) -> datetime | None:
        candidates: list[str] = []
        for tag in soup.find_all("time"):
            candidates.extend([tag.get("datetime", ""), tag.get_text(" ", strip=True)])
        for tag in soup.find_all("meta"):
            key = (tag.get("property") or tag.get("name") or tag.get("itemprop") or "").lower()
            if key in {"article:published_time", "datepublished", "date", "pubdate"}:
                candidates.append(tag.get("content", ""))
        for script in soup.find_all("script", type="application/ld+json"):
            try:
                value = json.loads(script.string or script.get_text())
            except (json.JSONDecodeError, TypeError):
                continue
            objects = value if isinstance(value, list) else [value]
            for item in objects:
                if isinstance(item, dict):
                    candidates.extend([item.get("datePublished", ""), item.get("dateCreated", "")])
        for candidate in candidates:
            parsed = cls.parse_date(candidate)
            if parsed:
                return parsed
        return None

    @classmethod
    def extract_article(cls, html: str, url: str) -> FetchedArticle | None:
        soup = BeautifulSoup(html, "html.parser")
        title_tag = soup.find("meta", property="og:title")
        title = cls.clean_text(title_tag.get("content") if title_tag else "")
        if not title:
            heading = soup.find("h1") or soup.find("title")
            title = cls.clean_text(heading.get_text(" ", strip=True) if heading else "")
        if not title:
            return None

        candidates: list[str] = []
        for selector in (
            "article", "[class*='entry-content']", "[class*='article-content']",
            "[class*='article-body']", "main",
        ):
            for element in soup.select(selector):
                text = cls.clean_text(element.get_text(" ", strip=True))
                if len(text) >= 120:
                    candidates.append(text)
        body = max(candidates, key=len, default="")
        published_at = cls.extract_date(soup)
        raw_metadata = {
            "source_adapter": cls.source_key,
            "host": urlparse(url).netloc,
        }
        return FetchedArticle(
            source_url=url,
            canonical_url=url,
            title_original=title,
            body_original=body or None,
            language=cls.detect_language(f"{title} {body}"),
            published_at=published_at,
            raw_metadata=raw_metadata,
        )

    @staticmethod
    def matches_ticker(article: FetchedArticle, ticker: str) -> bool:
        alias = EGX_COMPANIES[ticker]
        title = article.title_original
        body = article.body_original or ""
        pattern = rf"(?<![A-Za-z]){re.escape(alias)}(?![A-Za-z])"
        ticker_pattern = rf"(?<![A-Za-z]){re.escape(ticker)}(?![A-Za-z])"
        if re.search(pattern, title, re.IGNORECASE) or re.search(ticker_pattern, title, re.IGNORECASE):
            return True
        body_hits = len(re.findall(pattern, body, re.IGNORECASE))
        body_hits += len(re.findall(ticker_pattern, body, re.IGNORECASE))
        return body_hits >= 2

    async def _search(self, client: httpx.AsyncClient, query: str) -> list[tuple[str, str | None]]:
        endpoint = (
            f"{BASE_URL}/wp-json/wp/v2/posts?search={quote_plus(query)}"
            "&per_page=20&orderby=date&order=desc&_fields=link,date,title"
        )
        response = await client.get(endpoint)
        response.raise_for_status()
        rows = response.json()
        return [(row.get("link", ""), row.get("date")) for row in rows if row.get("link")]

    async def fetch_articles(self, *, since: datetime | None = None) -> list[FetchedArticle]:
        cutoff = since or (datetime.now(timezone.utc) - timedelta(days=MAX_AGE_DAYS))
        if cutoff.tzinfo is None:
            raise ValueError("since must be timezone-aware")
        headers = {"User-Agent": "FinMindNewsResearchBot/1.0", "Accept-Language": "ar,en;q=0.8"}
        results: list[FetchedArticle] = []
        seen: set[str] = set()
        async with httpx.AsyncClient(headers=headers, timeout=self.timeout_seconds, follow_redirects=True) as client:
            for ticker in self.tickers:
                print(f"Searching Daily News Egypt for {ticker} ({EGX_COMPANIES[ticker]})...")
                candidates: list[str] = []
                for query in (ticker, EGX_COMPANIES[ticker]):
                    try:
                        candidates.extend(url for url, _ in await self._search(client, query))
                    except (httpx.HTTPError, ValueError) as exc:
                        print(f"Search failed for {ticker}: {exc}")
                        break
                for url in dict.fromkeys(candidates):
                    if url in seen:
                        continue
                    try:
                        response = await client.get(url)
                        response.raise_for_status()
                        article = self.extract_article(response.text, url)
                    except (httpx.HTTPError, ValueError) as exc:
                        print(f"Article failed: {url} ({exc})")
                        continue
                    if article is None or not self.matches_ticker(article, ticker):
                        continue
                    if article.published_at and article.published_at < cutoff:
                        continue
                    article.raw_metadata["daily_news_listing_tickers"] = [ticker]
                    article.raw_metadata["discovered_via"] = "daily_news_wordpress_search"
                    seen.add(url)
                    results.append(article)
                    print(json.dumps(article.model_dump(mode="json"), ensure_ascii=False, indent=2))
                    if sum(1 for item in results if ticker in item.raw_metadata.get("daily_news_listing_tickers", [])) >= self.per_ticker:
                        break
        print(f"Daily News Egypt preview complete: {len(results)} articles")
        return results


async def main() -> None:
    source = DailyNewsPreviewSource()
    await source.fetch_articles()


if __name__ == "__main__":
    asyncio.run(main())
