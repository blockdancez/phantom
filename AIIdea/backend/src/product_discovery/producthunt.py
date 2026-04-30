"""Product Hunt discovery via official GraphQL API v2.

Docs: https://api.producthunt.com/v2/docs

Why GraphQL over the HTML/Playwright extractor:
- The PH list page is a SPA; rendering + LLM extraction is slow + expensive.
- The API gives canonical fields (name, tagline, website) without parsing.
- We already have PRODUCTHUNT_API_TOKEN in Settings.
"""
from __future__ import annotations

from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import httpx
import structlog

from src.product_discovery.types import DiscoveredProduct

logger = structlog.get_logger()

GRAPHQL_ENDPOINT = "https://api.producthunt.com/v2/api/graphql"

_QUERY = """
query TopRanked($first: Int!) {
  posts(order: RANKING, first: $first) {
    edges {
      node {
        id
        slug
        name
        tagline
        website
        url
      }
    }
  }
}
"""


def _strip_tracking(url: str) -> str:
    """Drop utm_* / ref / fbclid query params so candidate URLs dedupe cleanly."""
    parts = urlparse(url)
    if not parts.query:
        return url
    kept = [
        (k, v)
        for (k, v) in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith(("utm_", "ref", "fbclid", "gclid", "mc_"))
    ]
    return urlunparse(parts._replace(query=urlencode(kept)))


# PH wraps every outbound URL (Post.website + Post.productLinks.url) in a
# /r/<id> Cloudflare-gated tracking redirect. Headless HTTP clients (HEAD/GET)
# get 403 cf-mitigated; headless Chromium hits the JS challenge and times out
# in 25–30s per link, which would burn ~10 minutes per discovery tick.
# We accept the short link as-is — the experience agent runs a real Chromium
# session that has cookies / state to clear CF on the spot, so the URL still
# resolves at experience time, just not at discovery time.


async def fetch_top_products(token: str, first: int = 20) -> list[DiscoveredProduct]:
    if not token:
        logger.warning("Product Hunt token 缺失")
        return []

    async with httpx.AsyncClient(timeout=30.0) as client:
        try:
            resp = await client.post(
                GRAPHQL_ENDPOINT,
                json={"query": _QUERY, "variables": {"first": first}},
                headers={
                    "Authorization": f"Bearer {token}",
                    "Accept": "application/json",
                    "Content-Type": "application/json",
                },
            )
        except httpx.HTTPError as exc:
            logger.warning("Product Hunt 请求失败", error=str(exc))
            return []

    if resp.status_code != 200:
        logger.warning(
            "producthunt_non_200",
            status=resp.status_code,
            body=resp.text[:300],
        )
        return []

    payload = resp.json()
    if "errors" in payload:
        logger.warning("Product Hunt GraphQL 错误", errors=payload["errors"][:3])
        return []

    edges = payload.get("data", {}).get("posts", {}).get("edges", [])
    raw: list[tuple[str, str, str | None, str]] = []
    for edge in edges:
        node = edge.get("node") or {}
        # Prefer the product's own website over the PH listing URL — we want
        # to experience the product itself, not its launch page.
        homepage = (node.get("website") or "").strip() or (node.get("url") or "").strip()
        slug = (node.get("slug") or "").strip()
        name = (node.get("name") or "").strip()
        if not (homepage and slug and name):
            continue
        raw.append((slug, name, node.get("tagline") or None, homepage))

    out: list[DiscoveredProduct] = []
    for slug, name, tagline, raw_url in raw:
        out.append(
            DiscoveredProduct(
                slug=f"ph-{slug}",
                name=name,
                homepage_url=_strip_tracking(raw_url),
                tagline=tagline,
                discovered_from="producthunt",
            )
        )
    logger.info("Product Hunt 发现", count=len(out))
    return out
