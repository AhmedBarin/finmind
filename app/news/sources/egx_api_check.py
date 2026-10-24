import asyncio

from playwright.async_api import async_playwright


MEDIA_CENTER_URL = "https://beta.egx.com.eg/en/media-center"
NEWS_API_URL = "https://beta.egx.com.eg/api/bff/egx/news-search"


async def main() -> None:
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(
            channel="msedge",
            headless=True,
        )

        try:
            page = await browser.new_page()

            # Wait for the Media Center page itself to trigger its news-search request.
            async with page.expect_response(
                lambda response: (
                    response.url.split("?")[0] == NEWS_API_URL
                    and response.request.method == "POST"
                ),
                timeout=60_000,
            ) as response_info:
                await page.goto(
                    MEDIA_CENTER_URL,
                    wait_until="domcontentloaded",
                )

            response = await response_info.value
            print("EGX API status:", response.status)

            if response.status != 200:
                print("Response body:", (await response.text())[:1000])
                return

            result = await response.json()
            print("Total updates:", result.get("totalCount"))
            print("Total pages:", result.get("totalPages"))
            print("Items on first page:", len(result.get("data", [])))

            for item in result.get("data", [])[:3]:
                print(
                    item.get("code"),
                    item.get("dateStamp"),
                    item.get("heading"),
                )
        finally:
            await browser.close()


if __name__ == "__main__":
    asyncio.run(main())