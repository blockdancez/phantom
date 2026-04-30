"""Config-driven JSON API collector.

For sources that expose a simple JSON list endpoint (array or nested array
accessed via a dot path). Maps each element to a SourceItem dict using the
field names declared in :class:`SourceConfig`.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import structlog

from src.collectors.base import BaseCollector
from src.collectors.sources_registry import SourceConfig

logger = structlog.get_logger()


class GenericJSONCollector(BaseCollector):
    def __init__(self, config: SourceConfig):
        super().__init__()
        self.config = config

    def _extract_list(self, data: Any) -> list[Any]:
        path = self.config.items_path
        if not path:
            return data if isinstance(data, list) else []
        node: Any = data
        for key in path.split("."):
            if isinstance(node, dict):
                node = node.get(key)
            else:
                return []
        return node if isinstance(node, list) else []

    def _resolve_url(self, raw: str) -> str:
        if not raw:
            return ""
        if raw.startswith(("http://", "https://")):
            return raw
        prefix = self.config.url_prefix or ""
        if not prefix:
            return raw
        return prefix.rstrip("/") + "/" + raw.lstrip("/")

    async def collect(self, limit: int = 30) -> list[dict]:
        cfg = self.config
        if not (cfg.title_field and cfg.url_field):
            logger.warning("通用 JSON 字段缺失", source=cfg.name)
            return []

        try:
            data = await self._fetch_json(cfg.url)
        except Exception:
            logger.exception("通用 JSON 抓取失败", source=cfg.name)
            return []

        raw_items = self._extract_list(data)
        logger.info("通用 JSON 抽取条目", source=cfg.name, count=len(raw_items))

        out: list[dict] = []
        seen: set[str] = set()
        now = datetime.now(timezone.utc).isoformat()

        for entry in raw_items[: max(limit * 2, limit)]:
            if not isinstance(entry, dict):
                continue
            title = entry.get(cfg.title_field) or ""
            if not isinstance(title, str) or not title:
                continue
            url = self._resolve_url(str(entry.get(cfg.url_field) or ""))
            if not url or url in seen:
                continue

            if len(title) > 490:
                title = title[:490] + "..."

            content = ""
            if cfg.content_field:
                val = entry.get(cfg.content_field)
                if isinstance(val, str):
                    content = val

            seen.add(url)
            out.append(
                {
                    "source": cfg.name,
                    "title": title,
                    "url": url,
                    "content": content,
                    "raw_data": {"api_source": cfg.url, "entry": entry},
                    "collected_at": now,
                }
            )
            if len(out) >= limit:
                break

        return out
