"""One-shot source probe.

For each candidate site, try common RSS paths and autodiscover via homepage
<link rel="alternate">. Classify each as rss/html/skip and write a Markdown
report to backend/scripts/sources_probe_report.md.

Usage:
    PYTHONPATH=backend python backend/scripts/probe_sources.py
"""

from __future__ import annotations

import asyncio
import re
import sys
import uuid
from dataclasses import dataclass
from pathlib import Path

import httpx
import structlog

LOG = structlog.get_logger()

RSS_PATHS = [
    "/feed",
    "/feed/",
    "/rss",
    "/rss.xml",
    "/feed.xml",
    "/atom.xml",
    "/index.xml",
]

RSS_CONTENT_TYPES = (
    "application/rss+xml",
    "application/atom+xml",
    "application/xml",
    "text/xml",
)

RSS_LINK_RE = re.compile(
    r'<link[^>]+rel=["\']alternate["\'][^>]+type=["\']application/(?:rss|atom)\+xml["\'][^>]*>',
    re.IGNORECASE,
)
HREF_RE = re.compile(r'href=["\']([^"\']+)["\']', re.IGNORECASE)

# User list (35) — a few cleaned up for ambiguity
USER_SITES: list[str] = [
    "https://www.producthunt.com",
    "https://twelve.tools",
    "https://fazier.com",
    "https://turbo0.com",
    "https://findly.tools",
    "https://uneed.best",
    "https://peerpush.net",
    "https://toolfame.com",
    "https://tinylaunch.com",
    "https://neeed.directory",
    "https://trustmrr.com",
    "https://foundrlist.com",
    "https://indie.deals",
    "https://microlaunch.net",
    "https://startupslab.site",
    "https://trylaunch.ai",
    "https://rankinpublic.xyz",
    "https://toolfolio.io",
    "https://confettisaas.com",
    "https://launch.cab",
    "https://go-publicly.com",
    "https://indietools.app",
    "https://selected.site",
    "https://saascity.io",
    "https://endors.me",
    # "everfeatured" — unknown TLD, skipping
    "https://stackovery.com",
    "https://auraplusplus.com",
    "https://shipstry.com",
    "https://betterlaunch.co",
    "https://desifounder.com",
    "https://oksaas.co",
    "https://showmeyour.site",
    "https://agentwork.tools",
    "https://marketingdb.live",
    "https://saasstars.com",
]

# My curated additions — high-signal AI content (mostly RSS)
CURATED_SITES: list[tuple[str, str]] = [
    ("arxiv:cs.AI", "http://export.arxiv.org/rss/cs.AI"),
    ("arxiv:cs.LG", "http://export.arxiv.org/rss/cs.LG"),
    ("arxiv:cs.CL", "http://export.arxiv.org/rss/cs.CL"),
    ("devto:ai", "https://dev.to/feed/tag/ai"),
    ("devto:machinelearning", "https://dev.to/feed/tag/machinelearning"),
    ("devto:llm", "https://dev.to/feed/tag/llm"),
    ("lobsters", "https://lobste.rs/rss"),
    ("betalist", "https://betalist.com/feed"),
    ("indiehackers", "https://www.indiehackers.com/rss.xml"),
    ("hackernoon:ai", "https://hackernoon.com/tagged/ai/feed"),
    ("smol_ai_news", "https://buttondown.com/ainews/rss"),
    ("paperswithcode_latest", "https://paperswithcode.com/latest/rss"),
    # APIs (explicitly JSON, not RSS)
    ("huggingface:trending_models", "https://huggingface.co/api/models?sort=trending&limit=30"),
    ("huggingface:trending_spaces", "https://huggingface.co/api/spaces?sort=trending&limit=30"),
]


@dataclass
class ProbeResult:
    name: str
    homepage: str
    status: str  # "rss" | "html" | "skip"
    rss_url: str | None = None
    note: str = ""


def looks_like_feed(text: str, content_type: str) -> bool:
    if any(ct in content_type.lower() for ct in RSS_CONTENT_TYPES):
        return True
    head = text[:2000].lower()
    return "<rss" in head or "<feed" in head or "<?xml" in head and "rss" in head


async def try_url(
    client: httpx.AsyncClient, url: str, request_id: str
) -> tuple[bool, str, str]:
    """Return (ok_as_feed, content_type, body_snippet)."""
    try:
        r = await client.get(url, follow_redirects=True, timeout=10.0)
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        LOG.debug("probe_fetch_failed", url=url, error=str(exc), request_id=request_id)
        return False, "", ""
    if r.status_code >= 400:
        return False, "", ""
    ct = r.headers.get("content-type", "")
    text = r.text
    return looks_like_feed(text, ct), ct, text[:500]


async def probe_site(
    client: httpx.AsyncClient, name: str, homepage: str
) -> ProbeResult:
    request_id = str(uuid.uuid4())
    log = LOG.bind(site=name, request_id=request_id)
    log.info("probe_start", homepage=homepage)

    # 1. Try common RSS paths
    for p in RSS_PATHS:
        candidate = homepage.rstrip("/") + p
        ok, ct, _ = await try_url(client, candidate, request_id)
        if ok:
            log.info("probe_rss_found", rss_url=candidate, content_type=ct)
            return ProbeResult(name=name, homepage=homepage, status="rss", rss_url=candidate)

    # 2. Autodiscover from homepage
    try:
        r = await client.get(homepage, follow_redirects=True, timeout=10.0)
        if r.status_code < 400:
            m = RSS_LINK_RE.search(r.text)
            if m:
                href = HREF_RE.search(m.group(0))
                if href:
                    rss_url = href.group(1)
                    if rss_url.startswith("/"):
                        rss_url = homepage.rstrip("/") + rss_url
                    ok, ct, _ = await try_url(client, rss_url, request_id)
                    if ok:
                        log.info("probe_rss_autodiscover", rss_url=rss_url)
                        return ProbeResult(
                            name=name, homepage=homepage, status="rss", rss_url=rss_url
                        )
            log.info("probe_html_only")
            return ProbeResult(
                name=name,
                homepage=homepage,
                status="html",
                note="homepage reachable, no RSS",
            )
        log.warning("probe_homepage_bad_status", status=r.status_code)
        return ProbeResult(
            name=name, homepage=homepage, status="skip", note=f"homepage HTTP {r.status_code}"
        )
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        log.warning("probe_homepage_failed", error=str(exc))
        return ProbeResult(
            name=name, homepage=homepage, status="skip", note=f"unreachable: {exc}"
        )


async def probe_feed_direct(
    client: httpx.AsyncClient, name: str, feed_url: str
) -> ProbeResult:
    """For curated RSS/JSON URLs — probe the exact URL, not the homepage."""
    request_id = str(uuid.uuid4())
    log = LOG.bind(site=name, request_id=request_id)
    log.info("probe_direct_start", url=feed_url)

    is_json_api = "huggingface.co/api" in feed_url

    try:
        r = await client.get(feed_url, follow_redirects=True, timeout=15.0)
    except (httpx.RequestError, httpx.TimeoutException) as exc:
        log.warning("probe_direct_failed", error=str(exc))
        return ProbeResult(
            name=name, homepage=feed_url, status="skip", note=f"unreachable: {exc}"
        )

    if r.status_code >= 400:
        return ProbeResult(
            name=name, homepage=feed_url, status="skip", note=f"HTTP {r.status_code}"
        )

    if is_json_api:
        # Check JSON parseable and non-empty list
        try:
            data = r.json()
        except Exception as exc:  # noqa: BLE001
            return ProbeResult(
                name=name, homepage=feed_url, status="skip", note=f"json parse error: {exc}"
            )
        if isinstance(data, list) and data:
            log.info("probe_json_ok", count=len(data))
            return ProbeResult(
                name=name,
                homepage=feed_url,
                status="html",  # we'll mark as json separately in registry
                rss_url=feed_url,
                note=f"JSON API, {len(data)} items",
            )
        return ProbeResult(
            name=name, homepage=feed_url, status="skip", note="JSON empty or wrong shape"
        )

    ct = r.headers.get("content-type", "")
    if looks_like_feed(r.text, ct):
        log.info("probe_direct_rss_ok", content_type=ct)
        return ProbeResult(
            name=name, homepage=feed_url, status="rss", rss_url=feed_url
        )
    return ProbeResult(
        name=name, homepage=feed_url, status="skip", note=f"not a feed (content-type={ct})"
    )


async def main() -> int:
    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) "
            "AppleWebKit/537.36 (KHTML, like Gecko) "
            "Chrome/120.0.0.0 Safari/537.36 AIIdeaProbe/1.0"
        )
    }
    results: list[ProbeResult] = []

    async with httpx.AsyncClient(headers=headers) as client:
        # Probe user sites in parallel (batches of 8 to stay polite)
        sem = asyncio.Semaphore(8)

        async def guarded(coro):
            async with sem:
                return await coro

        user_tasks = [
            guarded(probe_site(client, url.replace("https://", "").replace("www.", ""), url))
            for url in USER_SITES
        ]
        curated_tasks = [
            guarded(probe_feed_direct(client, name, url)) for name, url in CURATED_SITES
        ]
        results = await asyncio.gather(*user_tasks, *curated_tasks)

    # Write report
    report_path = Path(__file__).parent / "sources_probe_report.md"
    lines: list[str] = ["# Source Probe Report", ""]
    buckets = {"rss": [], "html": [], "skip": []}
    for r in results:
        buckets[r.status].append(r)

    for status, title in [
        ("rss", "## ✅ RSS (ready to use)"),
        ("html", "## 🔧 HTML / JSON API (needs selector or custom parser)"),
        ("skip", "## ❌ Skipped (unreachable / no feed)"),
    ]:
        lines.append(title)
        lines.append("")
        lines.append("| Name | URL | Note |")
        lines.append("|---|---|---|")
        for r in buckets[status]:
            url = r.rss_url or r.homepage
            lines.append(f"| `{r.name}` | {url} | {r.note} |")
        lines.append("")

    lines.append(f"**Total:** {len(results)} | "
                 f"RSS: {len(buckets['rss'])} | "
                 f"HTML/JSON: {len(buckets['html'])} | "
                 f"Skip: {len(buckets['skip'])}")
    report_path.write_text("\n".join(lines), encoding="utf-8")
    LOG.info("report_written", path=str(report_path), counts={k: len(v) for k, v in buckets.items()})
    print(f"\nReport written to {report_path}")
    print(f"RSS: {len(buckets['rss'])}  HTML/JSON: {len(buckets['html'])}  Skip: {len(buckets['skip'])}")
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
