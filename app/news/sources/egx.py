import asyncio
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx


EGX_MEDIA_CENTER = "https://beta.egx.com.eg/en/media-center"
EGX_API_URL = "https://beta.egx.com.eg/api/bff/egx/news-search"
EGX_CAIRO = ZoneInfo("Africa/Cairo")

EGX_SECTION_IDS = [3, 4, 5, 6, 7, 8, 16, 10, 11, 12, 13]


async def fetch_news_page(
    client: httpx.AsyncClient,
    page_number: int,
    date_from: str,
    date_to: str,
) -> dict:
    payload = {
        "marketSessionNews": False,
        "secIds": EGX_SECTION_IDS,
        "interval": 50,
        "pageNumber": page_number,
        "pageSize": 20,
        "count": 50,
        "dateFrom": date_from,
        "dateTo": date_to,
    }

    response = await client.post(EGX_API_URL, json=payload)

    if response.status_code != 200:
        print("EGX response status:", response.status_code)
        print("EGX response body:", response.text[:1000])
        print(
            "EGX response headers:",
            {
                "server": response.headers.get("server"),
                "content-type": response.headers.get("content-type"),
                "date": response.headers.get("date"),
            },
        )
        response.raise_for_status()

    result = response.json()

    if not result.get("success"):
        raise RuntimeError(
            f"EGX news search failed: {result.get('message')}"
        )

    return result


async def main() -> None:
    today = datetime.now(EGX_CAIRO).date()
    date_from = (today - timedelta(days=30)).isoformat()
    date_to = today.isoformat()

    headers = {
        "User-Agent": "Mozilla/5.0",
        "Accept": "application/json",
        "Accept-Language": "en,ar;q=0.9",
        "Origin": "https://beta.egx.com.eg",
        "Referer": EGX_MEDIA_CENTER,
    }

    async with httpx.AsyncClient(
        timeout=30,
        follow_redirects=True,
        headers=headers,
    ) as client:
        # Open the page first; the same client keeps any cookies it receives.
        media_response = await client.get(EGX_MEDIA_CENTER)
        print("Media Center status:", media_response.status_code)
        media_response.raise_for_status()

        # Diagnostic only: fetch page 1; do not save anything to PostgreSQL.
        result = await fetch_news_page(
            client,
            page_number=1,
            date_from=date_from,
            date_to=date_to,
        )

    print("API request succeeded.")
    print("Total updates:", result.get("totalCount"))
    print("Total pages:", result.get("totalPages"))
    print("Items on this page:", len(result.get("data", [])))

    for item in result.get("data", [])[:3]:
        print(
            item.get("code"),
            item.get("dateStamp"),
            item.get("heading"),
        )


if __name__ == "__main__":
    asyncio.run(main())