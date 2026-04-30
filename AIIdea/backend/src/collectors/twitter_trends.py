import structlog
from datetime import datetime, timezone

from src.collectors.base import BaseCollector

logger = structlog.get_logger()


class TwitterTrendsCollector(BaseCollector):
    async def _scrape_trends(self) -> list[dict]:
        from playwright.async_api import async_playwright

        trends = []
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page()

            try:
                await page.goto("https://trends24.in/united-states/", wait_until="domcontentloaded", timeout=30000)
                trend_cards = await page.query_selector_all("ol.trend-card__list li a")

                for card in trend_cards[:50]:
                    text = await card.inner_text()
                    href = await card.get_attribute("href")
                    trends.append({
                        "name": text.strip(),
                        "url": href or f"https://x.com/search?q={text.strip()}",
                        "tweet_volume": None,
                    })
            except Exception:
                logger.exception("Twitter trends 抓取失败")
            finally:
                await browser.close()

        return trends

    async def collect(self, limit: int = 30) -> list[dict]:
        logger.info("Twitter trends 采集开始", limit=limit)

        raw_trends = await self._scrape_trends()
        items = []

        for trend in raw_trends[:limit]:
            items.append({
                "source": "twitter_trends",
                "title": trend["name"],
                "url": trend["url"],
                "content": f"Trending topic: {trend['name']}. Tweet volume: {trend.get('tweet_volume', 'N/A')}",
                "raw_data": trend,
                "collected_at": datetime.now(timezone.utc).isoformat(),
            })

        logger.info("Twitter trends 采集完成", count=len(items))
        return items
