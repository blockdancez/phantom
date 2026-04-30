"""Orchestrate one discovery tick across all configured sources.

Per source: fetch top N candidates, then upsert into ``product_candidates``
keyed by ``homepage_url``. The pool is append-only — existing rows are left
untouched (we don't refresh tagline / discovered_from after the first sighting,
to keep the audit trail of who first surfaced the product).
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Iterable

import structlog
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from src.config import Settings
from src.db import get_async_session_factory
from src.models.product_candidate import ProductCandidate
from src.product_discovery.playwright_extractor import discover_via_llm
from src.product_discovery.producthunt import fetch_top_products
from src.product_discovery.types import DiscoveredProduct

logger = structlog.get_logger()

PER_SOURCE_LIMIT = 20


_HTML_SOURCES: list[tuple[str, str, str]] = [
    # (source_name_for_prompt, list_url, discovered_from_tag)
    ("Toolify.ai", "https://www.toolify.ai/", "toolify"),
    ("Traffic.cv", "https://traffic.cv/", "traffic_cv"),
]


async def _gather_all() -> list[DiscoveredProduct]:
    settings = Settings()  # type: ignore[call-arg]
    headless = settings.experience_headless

    bucket: list[DiscoveredProduct] = []

    # Source 1: Product Hunt (GraphQL)
    try:
        ph = await fetch_top_products(
            settings.producthunt_api_token, first=PER_SOURCE_LIMIT
        )
        bucket.extend(ph)
    except Exception:
        logger.exception("产品发现_Product Hunt 失败")

    # Sources 2+3: HTML + LLM extraction
    for source_name, list_url, tag in _HTML_SOURCES:
        try:
            items = await discover_via_llm(
                source_name=source_name,
                list_url=list_url,
                discovered_from=tag,
                headless=headless,
                top_n=PER_SOURCE_LIMIT,
            )
            bucket.extend(items)
        except Exception:
            logger.exception("产品发现_HTML 源失败", source=tag)

    return bucket


async def _upsert(items: Iterable[DiscoveredProduct]) -> tuple[int, int]:
    """Returns (inserted, skipped_existing)."""
    factory = get_async_session_factory()
    inserted = 0
    skipped = 0
    now = datetime.now(tz=timezone.utc)

    async with factory() as session:
        # Pre-load existing homepage_urls + slugs in one query so the common
        # case (most rows already exist) avoids per-row roundtrips.
        existing = await session.execute(
            select(ProductCandidate.homepage_url, ProductCandidate.slug)
        )
        url_seen: set[str] = set()
        slug_seen: set[str] = set()
        for url, slug in existing.all():
            url_seen.add(url)
            slug_seen.add(slug)

        for item in items:
            if item.homepage_url in url_seen:
                skipped += 1
                continue
            slug = item.slug
            # If slug collides (different source surfaced same product under
            # the same slug), append a suffix; URL uniqueness still wins.
            if slug in slug_seen:
                slug = f"{slug}-{int(now.timestamp())}"
            row = ProductCandidate(
                slug=slug,
                name=item.name,
                homepage_url=item.homepage_url,
                tagline=item.tagline,
                discovered_from=item.discovered_from,
                discovered_at=now,
                created_at=now,
                experience_count=0,
            )
            session.add(row)
            try:
                await session.flush()
            except IntegrityError:
                await session.rollback()
                skipped += 1
                continue
            url_seen.add(item.homepage_url)
            slug_seen.add(slug)
            inserted += 1
        await session.commit()

    return inserted, skipped


async def run_discovery_once() -> dict[str, int]:
    """Run all discovery sources; return summary counters."""
    items = await _gather_all()
    inserted, skipped = await _upsert(items)
    summary = {
        "fetched": len(items),
        "inserted": inserted,
        "skipped_existing": skipped,
    }
    logger.info("产品发现完成", **summary)
    return summary
