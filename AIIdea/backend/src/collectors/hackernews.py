import structlog
from datetime import datetime, timezone

from src.collectors.base import BaseCollector

logger = structlog.get_logger()

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"


class HackerNewsCollector(BaseCollector):
    async def collect(self, limit: int = 30) -> list[dict]:
        logger.info("HN 采集开始", limit=limit)

        top_story_ids = await self._fetch_json(f"{HN_API_BASE}/topstories.json")
        top_story_ids = top_story_ids[:limit]

        items = []
        for story_id in top_story_ids:
            try:
                raw = await self._fetch_json(f"{HN_API_BASE}/item/{story_id}.json")
                if not raw or raw.get("type") != "story":
                    continue

                item = {
                    "source": "hackernews",
                    "title": raw.get("title", ""),
                    "url": raw.get("url", f"https://news.ycombinator.com/item?id={story_id}"),
                    "content": raw.get("text", ""),
                    "raw_data": raw,
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                }
                items.append(item)
            except Exception:
                logger.exception("HN 单条抓取失败", story_id=story_id)
                continue

        logger.info("HN 采集完成", count=len(items))
        return items
