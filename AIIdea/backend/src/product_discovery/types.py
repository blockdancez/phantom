from dataclasses import dataclass


@dataclass(frozen=True)
class DiscoveredProduct:
    """A product surfaced by a discovery source.

    Discovery sources (Product Hunt API, Toolify HTML, traffic.cv HTML) all
    normalize to this shape so the runner can upsert into product_candidates
    uniformly. ``slug`` is what the source itself uses (Product Hunt slug,
    or a sanitized hostname-derived id for HTML sources) — guaranteed
    unique within a source, but the runner deduplicates across sources by
    homepage_url.
    """

    slug: str
    name: str
    homepage_url: str
    tagline: str | None
    discovered_from: str  # 'producthunt' | 'toolify' | 'traffic_cv'
