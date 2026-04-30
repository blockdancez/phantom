"""Config-driven HTML collector.

Takes a :class:`SourceConfig` with CSS selectors and pulls a list of items
from a single HTML page. One :class:`GenericHTMLCollector` instance per source.
"""

from __future__ import annotations

from datetime import datetime, timezone

import structlog
from bs4 import BeautifulSoup

from src.collectors.base import BaseCollector
from src.collectors.sources_registry import SourceConfig

logger = structlog.get_logger()


class GenericHTMLCollector(BaseCollector):
    def __init__(self, config: SourceConfig):
        super().__init__()
        self.config = config
        # Use a polite, recognizable UA for scraped sites
        self.client.headers.update(
            {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36 AIIdea/1.0"
                )
            }
        )

    def _name(self) -> str:
        return f"{self.__class__.__name__}[{self.config.name}]"

    def _resolve_url(self, href: str) -> str:
        if not href:
            return ""
        if href.startswith(("http://", "https://")):
            return href
        if href.startswith("/") and self.config.base_url:
            return self.config.base_url.rstrip("/") + href
        return href

    def _parse(self, html: str, limit: int) -> list[dict]:
        cfg = self.config
        if not cfg.item_selector:
            logger.warning("通用 HTML 缺 selector", source=cfg.name)
            return []

        soup = BeautifulSoup(html, "html.parser")
        elements = soup.select(cfg.item_selector)
        logger.info(
            "通用 HTML 抽取条目",
            source=cfg.name,
            count=len(elements),
            selector=cfg.item_selector,
        )

        items: list[dict] = []
        seen_urls: set[str] = set()
        now = datetime.now(timezone.utc).isoformat()

        for el in elements:
            # Determine the link element
            if cfg.link_is_item:
                link_el = el
            elif cfg.link_selector:
                link_el = el.select_one(cfg.link_selector)
            else:
                link_el = el.find("a")
            if link_el is None:
                continue

            href = link_el.get(cfg.link_attr, "")
            if not href:
                continue
            url = self._resolve_url(href)
            if not url or url in seen_urls:
                continue

            # Title resolution
            if cfg.title_is_link_text:
                title = link_el.get_text(" ", strip=True)
            elif cfg.title_selector:
                title_el = el.select_one(cfg.title_selector)
                title = title_el.get_text(" ", strip=True) if title_el else ""
            else:
                title = el.get_text(" ", strip=True)

            if not title:
                continue

            # Clamp overly long titles (SourceItem.title is VARCHAR(500))
            if len(title) > 490:
                title = title[:490] + "..."

            content = ""
            if cfg.content_selector:
                c_el = el.select_one(cfg.content_selector)
                if c_el:
                    content = c_el.get_text(" ", strip=True)

            seen_urls.add(url)
            items.append(
                {
                    "source": cfg.name,
                    "title": title,
                    "url": url,
                    "content": content,
                    "raw_data": {"html_source": cfg.url},
                    "collected_at": now,
                }
            )
            if len(items) >= limit:
                break

        return items

    async def collect(self, limit: int = 30) -> list[dict]:
        try:
            html = await self._fetch_html(self.config.url)
        except Exception:
            logger.exception("通用 HTML 抓取失败", source=self.config.name)
            return []
        return self._parse(html, limit)
