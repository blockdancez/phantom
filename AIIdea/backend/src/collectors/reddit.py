"""Reddit collector using public Atom feeds.

Reddit has been tightening access to its unauthenticated JSON endpoints
(``/r/{sub}/hot.json``) — requests get intermittent 403 / 429 responses and
entire subreddits occasionally start refusing anonymous JSON. The Atom feeds
at ``/r/{sub}.rss`` remain fully public, don't need a browser-like User-Agent
dance, and don't require any ``REDDIT_CLIENT_ID`` / ``_SECRET``.

The tradeoff: feeds don't expose upvote counts or comment counts. That's fine
because the Processor's analyzer derives its own hotness/novelty scores from
the article body, not from raw Reddit metadata.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone

import feedparser
import structlog

from src.collectors.base import BaseCollector

logger = structlog.get_logger()

# Mixed pool: a small set of AI / dev signals plus a larger set of consumer
# "pain point" and lifestyle subs so the analysis agent has enough material
# to generate ideas for non-technical everyday users.
DEFAULT_SUBREDDITS: list[str] = [
    # --- Tech / founder (kept small on purpose) ---
    "startups",
    "SaaS",
    "indiehackers",
    "SideProject",

    # --- Consumer daily pain points (gold for ideation) ---
    "mildlyinfuriating",
    "firstworldproblems",
    "LifeProTips",
    "YouShouldKnow",
    "AskReddit",
    "NoStupidQuestions",

    # --- Everyday life / productivity / finance ---
    "productivity",
    "getdisciplined",
    "personalfinance",
    "frugal",
    "BuyItForLife",

    # --- Family / health / self-improvement ---
    "Parenting",
    "loseit",
    "decidingtobebetter",
    "selfimprovement",

    # --- Career / small-business non-dev ---
    "smallbusiness",
    "Entrepreneur",
]

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    if not text:
        return ""
    return _WS_RE.sub(" ", _HTML_TAG_RE.sub(" ", text)).strip()


class RedditCollector(BaseCollector):
    def __init__(self, subreddits: list[str] | None = None):
        super().__init__()
        self.subreddits = subreddits or DEFAULT_SUBREDDITS
        # Reddit fingerprints requests aggressively — it rejects httpx with a
        # plain UA but accepts requests that look like a full Chrome browser
        # navigation (checks Sec-Fetch-* headers, Accept-Language, etc.).
        # This header bundle was verified to return 200 on /r/*.rss.
        self.client.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/131.0.0.0 Safari/537.36"
                ),
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                "Accept-Language": "en-US,en;q=0.9",
                "Accept-Encoding": "gzip, deflate, br",
                "Sec-Fetch-Dest": "document",
                "Sec-Fetch-Mode": "navigate",
                "Sec-Fetch-Site": "none",
                "Sec-Fetch-User": "?1",
                "Upgrade-Insecure-Requests": "1",
            }
        )

    async def collect(self, limit: int = 30) -> list[dict]:
        logger.info("Reddit 采集开始", subreddits=self.subreddits, limit=limit)
        all_items: list[dict] = []

        for sub in self.subreddits:
            feed_url = f"https://www.reddit.com/r/{sub}.rss"
            try:
                raw_xml = await self._fetch_html(feed_url)
            except Exception:
                logger.warning("Reddit 频道抓取失败", subreddit=sub)
                continue

            feed = feedparser.parse(raw_xml)
            if not feed.entries:
                logger.info("Reddit 频道空", subreddit=sub)
                continue

            count_before = len(all_items)
            # Each subreddit gets its own independent limit — do NOT trim the
            # combined list afterwards. (That was the old bug where only the
            # first sub ever contributed because limit was applied globally.)
            for entry in feed.entries[:limit]:
                permalink = entry.get("link", "")
                if not permalink:
                    continue
                title = entry.get("title", "")
                summary = entry.get("summary", "") or entry.get("description", "")
                content_text = _strip_html(summary)
                author = (
                    entry.get("author", "")
                    or (entry.get("author_detail", {}) or {}).get("name", "")
                )
                all_items.append(
                    {
                        # Source prefixed with the specific subreddit so the
                        # search_items tool can target consumer pain subs
                        # directly (e.g. source_contains="mildlyinfuriating").
                        "source": f"reddit:{sub}",
                        "title": title,
                        "url": permalink,
                        "content": content_text,
                        "raw_data": {
                            "subreddit": sub,
                            "author": author,
                            "published": entry.get("published", ""),
                            "feed_url": feed_url,
                        },
                        "collected_at": datetime.now(timezone.utc).isoformat(),
                    }
                )
            logger.info(
                "Reddit 频道完成",
                subreddit=sub,
                added=len(all_items) - count_before,
            )

        logger.info("Reddit 采集完成", count=len(all_items))
        return all_items
