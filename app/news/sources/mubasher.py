import asyncio
import json
import re
from datetime import datetime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
from playwright.async_api import async_playwright
from sqlalchemy import select

from app.core.database import SessionLocal
from app.news.models import NewsArticle, NewsSource


BASE_URL = "https://www.mubasher.info"
SOURCE_KEY = "mubasher"
MAX_PAGES = 60
ARTICLE_DELAY_SECONDS = 1
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


def clean_text(value: str | None) -> str:
    """Remove repeated whitespace from extracted text."""
    if not value:
        return ""
    return re.sub(r"\s+", " ", value).strip()


def article_id_from_url(url: str) -> str | None:
    """Get Mubasher's numeric article ID from its URL."""
    match = re.search(r"/news/(\d+)/", url)
    return match.group(1) if match else None


def is_article_url(url: str) -> bool:
    return article_id_from_url(url) is not None


def extract_title(soup: BeautifulSoup) -> str:
    """Read the title from OpenGraph metadata, H1, or the page title."""
    meta = soup.find("meta", property="og:title")
    if meta and meta.get("content"):
        return clean_text(meta["content"])

    h1 = soup.find("h1")
    if h1:
        return clean_text(h1.get_text(" ", strip=True))

    title = soup.find("title")
    if title:
        return clean_text(title.get_text(" ", strip=True))

    return ""


def extract_published_at(soup: BeautifulSoup) -> datetime | None:
    """Find the article's publication date and interpret it in Cairo time."""

    def parse_candidate(value: str | None) -> datetime | None:
        if not value:
            return None

        value = clean_text(value)
        value = value.translate(
            str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")
        )

        # ISO format, commonly used in HTML metadata and JSON-LD.
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=CAIRO_TZ)
            return parsed
        except ValueError:
            pass

        # Common numeric date formats.
        for date_format in (
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
        ):
            try:
                return datetime.strptime(value, date_format).replace(
                    tzinfo=CAIRO_TZ
                )
            except ValueError:
                continue

        # Arabic month names, for example: 24 أكتوبر 2026.
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

        match = re.search(
            r"(\d{1,2})\s+"
            r"(يناير|فبراير|مارس|أبريل|ابريل|مايو|يونيو|يوليو|"
            r"أغسطس|اغسطس|سبتمبر|أكتوبر|اكتوبر|نوفمبر|ديسمبر)"
            r"\s+(\d{4})",
            value,
        )
        if match:
            day = int(match.group(1))
            month = arabic_months[match.group(2)]
            year = int(match.group(3))
            try:
                return datetime(year, month, day, tzinfo=CAIRO_TZ)
            except ValueError:
                pass

        # Common English month formats.
        for date_format in (
            "%d %B %Y",
            "%B %d, %Y",
            "%d %b %Y",
            "%b %d, %Y",
        ):
            try:
                return datetime.strptime(value, date_format).replace(
                    tzinfo=CAIRO_TZ
                )
            except ValueError:
                continue

        return None

    candidates = []

    # <time datetime="..."> or visible text inside a <time> element.
    for tag in soup.find_all("time"):
        candidates.append(tag.get("datetime"))
        candidates.append(tag.get_text(" ", strip=True))

    # Publication metadata in the page head.
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
            candidates.append(meta.get("content"))

    # Schema.org publication date.
    for element in soup.select('[itemprop="datePublished"]'):
        candidates.append(element.get("content"))
        candidates.append(element.get("datetime"))
        candidates.append(element.get_text(" ", strip=True))

    # JSON-LD publication date.
    def collect_jsonld_dates(value):
        if isinstance(value, dict):
            for key, item in value.items():
                if key in {"datePublished", "dateCreated"}:
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

    # Some pages put the visible publication date in a date/publish element.
    for element in soup.select(
        '[class*="publish"], [class*="Publish"], '
        '[class*="date"], [class*="Date"]'
    ):
        text = element.get_text(" ", strip=True)
        if text and len(text) < 100:
            candidates.append(text)

    for candidate in candidates:
        parsed = parse_candidate(candidate)
        if parsed:
            return parsed

    return None


def is_premium_locked(text: str) -> bool:
    """Detect a paywall notice and do not try to bypass it."""
    return any(phrase in text for phrase in PREMIUM_PHRASES)


def extract_body(soup: BeautifulSoup) -> str:
    """Extract the longest available article body from the page."""
    candidates = []

    for selector in CONTENT_SELECTORS:
        for element in soup.select(selector):
            text = clean_text(element.get_text(" ", strip=True))
            if len(text) > 150 and not is_premium_locked(text):
                candidates.append(text)

    # Some pages include the article body in JSON-LD.
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            raw = script.string or script.get_text()
            data = json.loads(raw)
            objects = data if isinstance(data, list) else [data]

            for obj in objects:
                if not isinstance(obj, dict):
                    continue

                article_body = obj.get("articleBody")
                if not article_body:
                    continue

                text = clean_text(
                    BeautifulSoup(
                        article_body,
                        "html.parser",
                    ).get_text(" ", strip=True)
                )

                if len(text) > 150 and not is_premium_locked(text):
                    candidates.append(text)

        except (json.JSONDecodeError, TypeError):
            continue

    return max(candidates, key=len, default="")


async def get_or_create_source(session) -> NewsSource:
    """Find the Mubasher source row, or create it on the first run."""
    source = await session.scalar(
        select(NewsSource).where(NewsSource.source_key == SOURCE_KEY)
    )

    if source:
        return source

    source = NewsSource(
        source_key=SOURCE_KEY,
        name="Mubasher",
        source_type="news_provider",
        base_url=BASE_URL,
        enabled=True,
        content_policy="full_text",
    )
    session.add(source)
    await session.commit()
    await session.refresh(source)
    return source


async def article_exists(
    session,
    source_id,
    external_article_id: str,
) -> bool:
    """Check the database so an article is not inserted twice."""
    article_id = await session.scalar(
        select(NewsArticle.id).where(
            NewsArticle.source_id == source_id,
            NewsArticle.external_article_id == external_article_id,
        )
    )
    return article_id is not None


async def save_article(session, source, data: dict) -> None:
    """Save one article and its metadata to PostgreSQL."""
    body = data["body"] or None

    article = NewsArticle(
        source_id=source.id,
        external_article_id=data["external_article_id"],
        source_url=data["url"],
        canonical_url=data["url"],
        title_original=data["title"],
        title_normalized=data["title"].casefold(),
        body_original=body,
        body_cleaned=body,
        body_excerpt=body[:500] if body else None,
        language="ar",
        published_at=data["published_at"],
        content_rights="full_text" if body else "metadata_only",
        processing_status=data["processing_status"],
    )

    session.add(article)
    await session.commit()


async def collect_page_links(page, ticker: str, page_number: int) -> list[str]:
    """Get article links from one Mubasher stock-news page."""
    listing_url = (
        f"{BASE_URL}/markets/EGX/stocks/{ticker}/news"
        f"?page={page_number}"
    )

    try:
        await page.goto(
            listing_url,
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await page.wait_for_timeout(3000)
    except Exception as exc:
        print(f"Could not load listing page {listing_url}: {exc}")
        return []

    hrefs = await page.locator("a").evaluate_all(
        "elements => elements.map(element => element.href)"
    )

    # Keep the order displayed by the site; the scraper uses newest-first
    # order to stop when it reaches an older article.
    links = []
    seen_links = set()

    for href in hrefs:
        if not href:
            continue

        full_url = urljoin(BASE_URL, href)

        if is_article_url(full_url) and full_url not in seen_links:
            seen_links.add(full_url)
            links.append(full_url)

    return links


async def scrape_article(
    page,
    url: str,
    ticker: str,
    company: str,
) -> dict | None:
    """Read an article page; keep metadata if its body is locked/unavailable."""
    try:
        await page.goto(
            url,
            wait_until="domcontentloaded",
            timeout=60000,
        )
        await page.wait_for_timeout(4000)
        html = await page.content()
    except Exception as exc:
        print(f"Could not load article {url}: {exc}")
        return None

    soup = BeautifulSoup(html, "html.parser")
    page_text = clean_text(soup.get_text(" ", strip=True))
    title = extract_title(soup)

    if not title:
        print(f"Skipping article without a title: {url}")
        return None

    locked = is_premium_locked(page_text)
    body = "" if locked else extract_body(soup)

    if locked:
        print(f"Article is locked; saving metadata and URL only: {url}")
    elif not body:
        print(f"No article body found; saving metadata and URL: {url}")

    return {
        "external_article_id": article_id_from_url(url),
        "title": title,
        "published_at": extract_published_at(soup),
        "body": body,
        "url": url,
        "ticker": ticker,
        "company": company,
        "processing_status": "restricted" if locked else "pending",
    }


async def main() -> None:
    saved_count = 0
    skipped_count = 0
    failed_count = 0
    seen_ids_this_run = set()

    today = datetime.now(CAIRO_TZ).date()
    print(f"Saving Mubasher articles published on {today} only.")

    async with SessionLocal() as session:
        source = await get_or_create_source(session)

        async with async_playwright() as playwright:
            # Uses Microsoft Edge installed on this computer.
            browser = await playwright.chromium.launch(
                channel="msedge",
                headless=True,
            )
            context = await browser.new_context(locale="ar-EG")
            page = await context.new_page()

            try:
                for ticker, company in STOCKS.items():
                    print(f"\n=== {ticker}: {company} ===")
                    stop_ticker = False

                    for page_number in range(1, MAX_PAGES + 1):
                        print(f"Checking {ticker}, page {page_number}...")

                        links = await collect_page_links(
                            page,
                            ticker,
                            page_number,
                        )

                        if not links:
                            print(
                                f"No links on page {page_number}; "
                                f"stopping {ticker}."
                            )
                            break

                        page_ids = [
                            (link, article_id_from_url(link))
                            for link in links
                        ]
                        page_ids = [
                            (link, article_id)
                            for link, article_id in page_ids
                            if article_id
                        ]

                        existing_flags = []
                        for _, article_id in page_ids:
                            exists = await article_exists(
                                session,
                                source.id,
                                article_id,
                            )
                            existing_flags.append(exists)

                        if page_ids and all(existing_flags):
                            print(
                                f"Page {page_number} is already stored; "
                                f"stopping {ticker}."
                            )
                            break

                        for (url, article_id), exists in zip(
                            page_ids,
                            existing_flags,
                        ):
                            if exists or article_id in seen_ids_this_run:
                                skipped_count += 1
                                continue

                            data = await scrape_article(
                                page,
                                url,
                                ticker,
                                company,
                            )

                            if not data:
                                failed_count += 1
                                continue

                            published_at = data["published_at"]

                            if published_at is None:
                                print(
                                    "Skipping article without a readable "
                                    f"publication date: {url}"
                                )
                                skipped_count += 1
                                continue
                            print(
                                f"Read date: {published_at.astimezone(CAIRO_TZ)}"
                                f" | {data['title']}"
                            )
                            article_day = published_at.astimezone(
                                CAIRO_TZ
                            ).date()

                            if article_day < today:
                                print(
                                    f"Reached an older article for {ticker}; "
                                    "stopping this ticker's pagination."
                                )
                                stop_ticker = True
                                break

                            if article_day > today:
                                print(f"Skipping future-dated article: {url}")
                                skipped_count += 1
                                continue

                            seen_ids_this_run.add(article_id)

                            try:
                                await save_article(session, source, data)
                                saved_count += 1
                                print(f"Saved {article_id}: {data['title']}")
                            except Exception as exc:
                                await session.rollback()
                                failed_count += 1
                                print(
                                    f"Database save failed for "
                                    f"{article_id}: {exc}"
                                )

                            await asyncio.sleep(ARTICLE_DELAY_SECONDS)

                        if stop_ticker:
                            break

            finally:
                await browser.close()

    print("\n=== Finished ===")
    print(f"Saved: {saved_count}")
    print(f"Already stored / duplicate / skipped: {skipped_count}")
    print(f"Failed: {failed_count}")


if __name__ == "__main__":
    asyncio.run(main())