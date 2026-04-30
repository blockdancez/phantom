import feedparser
import structlog
from datetime import datetime, timezone

from src.collectors.base import BaseCollector

logger = structlog.get_logger()

DEFAULT_FEEDS = {
    "techcrunch": "https://techcrunch.com/feed/",
    "theverge": "https://www.theverge.com/rss/index.xml",
    "arstechnica": "https://feeds.arstechnica.com/arstechnica/index",
    "hackernoon": "https://hackernoon.com/feed",
    "thenewstack": "https://thenewstack.io/feed/",
}


class RSSCollector(BaseCollector):
    def __init__(self, feeds: dict[str, str] | None = None):
        super().__init__()
        self.feeds = feeds or DEFAULT_FEEDS
        # Many feed hosts (arxiv, some CDNs) block the default ``python-httpx``
        # User-Agent. Use a generic browser UA so they serve the feed.
        self.client.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36 AIIdea/1.0"
                ),
                "Accept": "application/rss+xml, application/atom+xml, application/xml;q=0.9, */*;q=0.8",
            }
        )

    async def collect(self, limit: int = 30) -> list[dict]:
        logger.info("RSS 采集开始", feed_count=len(self.feeds), limit=limit)
        all_items = []

        for name, url in self.feeds.items():
            try:
                raw_xml = await self._fetch_html(url)
                feed = feedparser.parse(raw_xml)

                for entry in feed.entries[:limit]:
                    item = {
                        "source": f"rss:{name}",
                        "title": entry.get("title", ""),
                        "url": entry.get("link", ""),
                        "content": entry.get("summary", entry.get("description", "")),
                        "raw_data": {
                            "feed_name": name,
                            "published": entry.get("published", ""),
                            "author": entry.get("author", ""),
                            "tags": [t.get("term", "") for t in entry.get("tags", [])],
                        },
                        "collected_at": datetime.now(timezone.utc).isoformat(),
                    }
                    all_items.append(item)
            except Exception:
                logger.exception("RSS 源抓取失败", feed_name=name, feed_url=url)
                continue

        logger.info("RSS 采集完成", count=len(all_items), feed_count=len(self.feeds))
        return all_items
