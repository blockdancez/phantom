import structlog
from datetime import datetime, timezone
from bs4 import BeautifulSoup

from src.collectors.base import BaseCollector

logger = structlog.get_logger()


class ProductHuntCollector(BaseCollector):
    async def collect(self, limit: int = 30) -> list[dict]:
        logger.info("Product Hunt 采集开始", limit=limit)
        items = []

        try:
            html = await self._fetch_html("https://www.producthunt.com/")
            soup = BeautifulSoup(html, "html.parser")

            for post in soup.select("[data-test='post-item']")[:limit]:
                title_el = post.select_one("h3")
                link_el = post.select_one("a[href*='/posts/']")
                desc_el = post.select_one("p")

                if not title_el or not link_el:
                    continue

                title = title_el.get_text(strip=True)
                href = link_el.get("href", "")
                url = f"https://www.producthunt.com{href}" if href.startswith("/") else href
                description = desc_el.get_text(strip=True) if desc_el else ""

                items.append({
                    "source": "producthunt",
                    "title": title,
                    "url": url,
                    "content": description,
                    "raw_data": {"page": "homepage"},
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                })
        except Exception:
            logger.exception("Product Hunt 抓取失败")

        logger.info("Product Hunt 采集完成", count=len(items))
        return items
