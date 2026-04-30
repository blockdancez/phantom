"""Content enrichment — Step 1 of the processing pipeline.

Many collectors store only a short title or one-paragraph summary in
``SourceItem.content``. Before the Analyzer can do anything meaningful, we
need the actual article text. The Enricher fetches the source URL (or the
appropriate API for GitHub / arXiv) and extracts the main body text.

Strategy is per-source:
- ``twitter_trends``      → skip (trend name only, no article)
- ``github_trending``     → GitHub API /repos/:owner/:repo/readme
- ``rss:arxiv_*``         → fetch arXiv abs page, extract abstract
- everything else         → generic trafilatura extraction

All network calls are best-effort. On failure the Enricher returns the
existing content so the Analyzer still gets something to chew on.
"""

from __future__ import annotations

import re
from typing import Final

import httpx
import structlog
import trafilatura

from src.models.source_item import SourceItem

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _strip_html(raw: str) -> str:
    """Cheap HTML → plain text. We don't need Beautiful Soup fidelity here —
    just enough to avoid feeding the LLM ``<p>`` / ``<h3>`` / ``<a>`` noise.
    """
    if not raw:
        return ""
    if "<" not in raw:
        return raw
    cleaned = _HTML_TAG_RE.sub(" ", raw)
    return _WS_RE.sub(" ", cleaned).strip()

logger = structlog.get_logger()

_USER_AGENT: Final[str] = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36 AIIdea/1.0"
)
_GITHUB_REPO_RE = re.compile(r"https?://github\.com/([^/]+)/([^/?#]+)")
_ARXIV_ID_RE = re.compile(r"arxiv\.org/abs/([0-9]+\.[0-9]+(?:v[0-9]+)?)")

_MAX_ENRICHED_LENGTH = 20_000


class Enricher:
    """Per-source content enrichment with graceful fallback."""

    def __init__(self) -> None:
        self.client = httpx.AsyncClient(
            timeout=20.0,
            follow_redirects=True,
            headers={"User-Agent": _USER_AGENT, "Accept": "*/*"},
        )

    async def close(self) -> None:
        await self.client.aclose()

    async def enrich(self, item: SourceItem) -> str:
        """Return the best available article text for this item.

        Never raises — any failure logs a warning and returns the item's
        existing ``content`` (possibly empty).
        """
        src = item.source or ""
        url = item.url or ""
        raw_fallback = item.content or ""
        # Always strip HTML from the fallback so the LLM never sees <p> / <h3>
        # / <a> noise regardless of which path we take.
        fallback = _strip_html(raw_fallback)

        log = logger.bind(source=src, url=url[:120])

        if src == "twitter_trends":
            # Nothing to enrich — trend strings have no article behind them.
            return fallback

        try:
            if src == "github_trending":
                text = await self._fetch_github_readme(url)
                return self._clamp(text or fallback)

            if src.startswith("rss:arxiv"):
                text = await self._fetch_arxiv(url)
                return self._clamp(text or fallback)

            text = await self._fetch_generic(url)
            # Trust trafilatura whenever it returns non-empty output. Extracted
            # clean text is almost always shorter than the original HTML, so
            # length comparison is the wrong heuristic.
            if text:
                return self._clamp(text)
            return self._clamp(fallback)
        except Exception:
            log.warning("富化失败", exc_info=True)
            return self._clamp(fallback)

    # ---------- private fetchers ----------

    async def _fetch_generic(self, url: str) -> str:
        if not url:
            return ""
        try:
            resp = await self.client.get(url)
        except httpx.HTTPError as exc:
            logger.debug("通用富化 HTTP 错误", url=url[:120], error=str(exc))
            return ""
        if resp.status_code >= 400:
            logger.debug("通用富化_状态码非 2xx", url=url[:120], status=resp.status_code)
            return ""

        # trafilatura is synchronous — but parsing is fast (ms), safe to call inline.
        text = trafilatura.extract(
            resp.text,
            include_comments=False,
            include_tables=False,
            favor_precision=True,
            no_fallback=False,
        )
        if text:
            logger.debug(
                "通用富化完成",
                url=url[:120],
                extracted_chars=len(text),
            )
            return text
        return ""

    async def _fetch_github_readme(self, url: str) -> str:
        match = _GITHUB_REPO_RE.search(url)
        if not match:
            return ""
        owner, repo = match.group(1), match.group(2).rstrip(".git")
        api_url = f"https://api.github.com/repos/{owner}/{repo}/readme"
        headers = {"Accept": "application/vnd.github.raw+json"}
        try:
            resp = await self.client.get(api_url, headers=headers)
        except httpx.HTTPError as exc:
            logger.debug("GitHub README HTTP 错误", url=url[:120], error=str(exc))
            return ""
        if resp.status_code >= 400:
            logger.debug("GitHub README_状态码非 2xx", url=url[:120], status=resp.status_code)
            return ""
        logger.debug("GitHub README 富化", repo=f"{owner}/{repo}", chars=len(resp.text))
        return resp.text

    async def _fetch_arxiv(self, url: str) -> str:
        # arxiv RSS link is usually http://arxiv.org/abs/2404.12345v1
        match = _ARXIV_ID_RE.search(url)
        if not match:
            # Fall back to generic fetch of whatever URL we have
            return await self._fetch_generic(url)
        arxiv_id = match.group(1)
        abs_url = f"https://arxiv.org/abs/{arxiv_id}"
        text = await self._fetch_generic(abs_url)
        if text:
            logger.debug("arXiv 摘要富化", id=arxiv_id, chars=len(text))
        return text

    @staticmethod
    def _clamp(text: str) -> str:
        if len(text) > _MAX_ENRICHED_LENGTH:
            return text[:_MAX_ENRICHED_LENGTH]
        return text
