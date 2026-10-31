import asyncio
import json
import re
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright

from app.news.schemas import FetchedArticle
from app.news.sources.base import NewsSourceAdapter


CAIRO_TZ = ZoneInfo("Africa/Cairo")

STOCKS = {
    "COMI": "CIB",
    "SWDY": "Elsewedy Electric",
    "ETEL": "Telecom Egypt",
    "TMGH": "Talaat Moustafa",
    "FWRY": "Fawry",
    "EAST": "Eastern Company",
    "EFID": "eFinance",
    "HRHO": "EFG Holding",
    "ORAS": "Orascom Construction",
    "ORHD": "Orascom Development",
    "ABUK": "Abu Qir Fertilizers",
    "MFPC": "MOPCO",
    "EGAL": "Egypt Aluminium",
    "SKPC": "SIDPEC",
    "AMOC": "Alexandria Mineral Oils",
    "JUFO": "Juhayna",
    "PHDC": "Palm Hills",
    "MASR": "Madinet Masr",
    "TAQA": "Taqa Arabia",
    "GBCO": "GB Corp",
}

PREMIUM_PHRASES = (
    "هذا الخبر خاص بخدمة الاخبار المدفوعة من مباشر",
    "هذا الخبر خاص بخدمة الأخبار المدفوعة من مباشر",
    "إذا كنت ترغب في الاشتراك",
    "اذا كنت ترغب في الاشتراك",
    "يمكنك الانتظار",
)

CONTENT_SELECTORS = (
    "[class*='article-content']",
    "[class*='article-body']",
    "[class*='articleBody']",
    "[class*='news-content']",
    "[class*='newsContent']",
    "[class*='news-body']",
    "[class*='content-body']",
    "[class*='contentBody']",
    "article",
)


class MubasherSource(NewsSourceAdapter):
    source_key = "mubasher"
    name = "Mubasher"
    base_url = "https://www.mubasher.info"
    source_type = "news_provider"
    content_policy = "full_text"

    max_pages = 60
    article_delay_seconds = 1

    @staticmethod
    def clean_text(value: str | None) -> str:
        if not value:
            return ""
        return re.sub(r"\s+", " ", value).strip()

    @staticmethod
    def article_id_from_url(url: str) -> str | None:
        match = re.search(r"/news/(\d+)(?:/|$)", url)
        return match.group(1) if match else None

    @classmethod
    def is_article_url(cls, url: str) -> bool:
        return cls.article_id_from_url(url) is not None

    @classmethod
    def extract_title(cls, soup: BeautifulSoup) -> str:
        meta = soup.find("meta", property="og:title")
        if meta and meta.get("content"):
            return cls.clean_text(meta["content"])

        h1 = soup.find("h1")
        if h1:
            return cls.clean_text(h1.get_text(" ", strip=True))

        title = soup.find("title")
        if title:
            return cls.clean_text(title.get_text(" ", strip=True))

        return ""


    @classmethod
    def extract_author(cls, soup: BeautifulSoup) -> str | None:
        for selector in (
            'meta[name="author"]',
            'meta[property="article:author"]',
            'meta[itemprop="author"]',
        ):
            tag = soup.select_one(selector)
            if tag and tag.get("content"):
                return cls.clean_text(tag["content"]) or None

        author_element = soup.select_one('[itemprop="author"]')
        if author_element:
            text = cls.clean_text(author_element.get_text(" ", strip=True))
            return text or None

        return None

    @classmethod
    def extract_updated_at(cls, soup: BeautifulSoup) -> datetime | None:
        candidates: list[str] = []

        for meta in soup.find_all("meta"):
            key = (
                meta.get("property")
                or meta.get("name")
                or meta.get("itemprop")
                or ""
            ).lower()

            if key in {"article:modified_time", "datemodified"}:
                value = meta.get("content")
                if value:
                    candidates.append(value)

        for element in soup.select('[itemprop="dateModified"]'):
            value = (
                element.get("content")
                or element.get("datetime")
                or element.get_text(" ", strip=True)
            )
            if value:
                candidates.append(value)

        for value in candidates:
            value = cls.clean_text(value)
            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=CAIRO_TZ)
                return parsed
            except ValueError:
                continue

        return None

    @classmethod
    def extract_raw_metadata(cls, soup: BeautifulSoup) -> dict[str, str]:
        metadata: dict[str, str] = {}

        for meta in soup.find_all("meta"):
            key = (
                meta.get("property")
                or meta.get("name")
                or meta.get("itemprop")
                or ""
            ).strip().lower()
            value = meta.get("content")

            if (
                value
                and (key.startswith("og:") or key.startswith("article:"))
            ):
                metadata[key] = cls.clean_text(value)

        return metadata

    
    @classmethod
    def extract_published_at(cls, soup: BeautifulSoup) -> datetime | None:
        candidates: list[str] = []

        for tag in soup.find_all("time"):
            candidates.append(tag.get("datetime", ""))
            candidates.append(tag.get_text(" ", strip=True))

        publication_meta_names = {
            "article:published_time",
            "datepublished",
            "publishdate",
            "pubdate",
            "date",
        }

        for meta in soup.find_all("meta"):
            meta_name = (
                meta.get("property")
                or meta.get("name")
                or meta.get("itemprop")
                or ""
            ).lower()

            if meta_name in publication_meta_names:
                candidates.append(meta.get("content", ""))

        for element in soup.select('[itemprop="datePublished"]'):
            candidates.append(element.get("content", ""))
            candidates.append(element.get("datetime", ""))
            candidates.append(element.get_text(" ", strip=True))

        def collect_jsonld_dates(value: object) -> None:
            if isinstance(value, dict):
                for key, item in value.items():
                    if key in {"datePublished", "dateCreated"} and isinstance(
                        item, str
                    ):
                        candidates.append(item)
                    collect_jsonld_dates(item)
            elif isinstance(value, list):
                for item in value:
                    collect_jsonld_dates(item)

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                raw = script.string or script.get_text()
                collect_jsonld_dates(json.loads(raw))
            except (json.JSONDecodeError, TypeError):
                continue

        for element in soup.select(
            '[class*="publish"], [class*="Publish"], '
            '[class*="date"], [class*="Date"]'
        ):
            text = element.get_text(" ", strip=True)
            if text and len(text) < 100:
                candidates.append(text)

        arabic_months = {
            "يناير": 1,
            "فبراير": 2,
            "مارس": 3,
            "أبريل": 4,
            "ابريل": 4,
            "مايو": 5,
            "يونيو": 6,
            "يوليو": 7,
            "أغسطس": 8,
            "اغسطس": 8,
            "سبتمبر": 9,
            "أكتوبر": 10,
            "اكتوبر": 10,
            "نوفمبر": 11,
            "ديسمبر": 12,
        }

        date_formats = (
            "%d/%m/%Y %H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y",
            "%d-%m-%Y %H:%M:%S",
            "%d-%m-%Y %H:%M",
            "%d-%m-%Y",
            "%Y/%m/%d %H:%M:%S",
            "%Y/%m/%d",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d",
            "%d %B %Y",
            "%B %d, %Y",
            "%d %b %Y",
            "%b %d, %Y",
        )

        for candidate in candidates:
            if not candidate:
                continue

            value = cls.clean_text(candidate)
            value = value.translate(
                str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
            )

            try:
                parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
                if parsed.tzinfo is None:
                    parsed = parsed.replace(tzinfo=CAIRO_TZ)
                return parsed
            except ValueError:
                pass

            for date_format in date_formats:
                try:
                    return datetime.strptime(value, date_format).replace(
                        tzinfo=CAIRO_TZ
                    )
                except ValueError:
                    continue

            month_pattern = (
                r"(\d{1,2})\s+"
                r"(يناير|فبراير|مارس|أبريل|ابريل|مايو|يونيو|يوليو|"
                r"أغسطس|اغسطس|سبتمبر|أكتوبر|اكتوبر|نوفمبر|ديسمبر)"
                r"\s+(\d{4})"
            )
            match = re.search(month_pattern, value)
            if match:
                try:
                    return datetime(
                        int(match.group(3)),
                        arabic_months[match.group(2)],
                        int(match.group(1)),
                        tzinfo=CAIRO_TZ,
                    )
                except ValueError:
                    continue

        return None

    @staticmethod
    def is_premium_locked(text: str) -> bool:
        return any(phrase in text for phrase in PREMIUM_PHRASES)

    @classmethod
    def extract_body(cls, soup: BeautifulSoup) -> str:
        candidates: list[str] = []

        for selector in CONTENT_SELECTORS:
            for element in soup.select(selector):
                text = cls.clean_text(element.get_text(" ", strip=True))
                if len(text) > 150 and not cls.is_premium_locked(text):
                    candidates.append(text)

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                raw = script.string or script.get_text()
                data = json.loads(raw)
                objects = data if isinstance(data, list) else [data]

                for item in objects:
                    if not isinstance(item, dict):
                        continue

                    article_body = item.get("articleBody")
                    if not isinstance(article_body, str):
                        continue

                    text = cls.clean_text(
                        BeautifulSoup(
                            article_body,
                            "html.parser",
                        ).get_text(" ", strip=True)
                    )
                    if len(text) > 150 and not cls.is_premium_locked(text):
                        candidates.append(text)

            except (json.JSONDecodeError, TypeError):
                continue

        return max(candidates, key=len, default="")

    async def collect_page_links(self, page, ticker: str, page_number: int) -> list[str]:
        listing_url = (
            f"{self.base_url}/markets/EGX/stocks/{ticker}/news"
            f"?page={page_number}"
        )

        try:
            response = await page.goto(
                listing_url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            if response and response.status >= 400:
                print(f"Listing returned HTTP {response.status}: {listing_url}")
                return []

            await page.wait_for_timeout(2000)
        except Exception as exc:
            print(f"Could not load listing page {listing_url}: {exc}")
            return []

        hrefs = await page.locator("a").evaluate_all(
            "elements => elements.map(element => element.href)"
        )

        links: list[str] = []
        seen: set[str] = set()

        for href in hrefs:
            if not href:
                continue

            full_url = urljoin(self.base_url, href)
            if self.is_article_url(full_url) and full_url not in seen:
                seen.add(full_url)
                links.append(full_url)

        return links

    async def scrape_article(self, page, url: str) -> FetchedArticle | None:
        try:
            response = await page.goto(
                url,
                wait_until="domcontentloaded",
                timeout=60000,
            )
            if response and response.status >= 400:
                print(f"Article returned HTTP {response.status}: {url}")
                return None

            await page.wait_for_timeout(2500)
            html = await page.content()
        except Exception as exc:
            print(f"Could not load article {url}: {exc}")
            return None

        soup = BeautifulSoup(html, "html.parser")
        page_text = self.clean_text(soup.get_text(" ", strip=True))
        title = self.extract_title(soup)

        if not title:
            print(f"Skipping article without a readable title: {url}")
            return None

        locked = self.is_premium_locked(page_text)
        body = "" if locked else self.extract_body(soup)

        if locked:
            print(f"Paywalled article; keeping metadata only: {url}")
        elif not body:
            print(f"No readable article body found: {url}")

        return FetchedArticle(
            external_article_id=self.article_id_from_url(url),
            source_url=url,
            canonical_url=url,
            title_original=title,
            body_original=body or None,
            published_at=self.extract_published_at(soup),
            language="ar",
            author=self.extract_author(soup),
            updated_at_source=self.extract_updated_at(soup),
            raw_metadata=self.extract_raw_metadata(soup),
        )

    async def fetch_articles(
        self,
        *,
        since: datetime | None = None,
    ) -> list[FetchedArticle]:
        now = datetime.now(CAIRO_TZ)
        today = now.date()

        if since is None:
            cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0)
        elif since.tzinfo is None:
            cutoff = since.replace(tzinfo=CAIRO_TZ)
        else:
            cutoff = since.astimezone(CAIRO_TZ)

        print(f"Fetching Mubasher articles since {cutoff.isoformat()}.")

        articles: list[FetchedArticle] = []
        seen_ids: set[str] = set()

        async with async_playwright() as playwright:
            browser = await playwright.chromium.launch(headless=True)
            try:
                context = await browser.new_context(locale="ar-EG")
                page = await context.new_page()

                for ticker, company in STOCKS.items():
                    print(f"\nChecking {ticker}: {company}")
                    stop_ticker = False

                    for page_number in range(1, self.max_pages + 1):
                        print(f"Checking listing page {page_number}...")
                        links = await self.collect_page_links(
                            page,
                            ticker,
                            page_number,
                        )

                        if not links:
                            print(f"No article links found; stopping {ticker}.")
                            break

                        for url in links:
                            article_id = self.article_id_from_url(url)
                            if not article_id or article_id in seen_ids:
                                continue

                            article = await self.scrape_article(page, url)
                            if article is None:
                                continue

                            if article.published_at is None:
                                print(f"Skipping article without a date: {url}")
                                continue

                            published_at = article.published_at
                            if published_at.tzinfo is None:
                                published_at = published_at.replace(
                                    tzinfo=CAIRO_TZ
                                )
                            published_at = published_at.astimezone(CAIRO_TZ)

                            if published_at.date() > today:
                                print(f"Skipping future-dated article: {url}")
                                continue

                            if published_at < cutoff:
                                print(
                                    f"Reached an older article for {ticker}; "
                                    "stopping this ticker's pagination."
                                )
                                stop_ticker = True
                                break

                            seen_ids.add(article_id)
                            articles.append(article)
                            print(f"Fetched {article_id}: {article.title_original}")

                            await asyncio.sleep(self.article_delay_seconds)

                        if stop_ticker:
                            break

            finally:
                await browser.close()

        print(f"\nFetched {len(articles)} articles from Mubasher.")
        return articles