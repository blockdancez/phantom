"""Source registry for config-driven collectors.

Each entry declares how to fetch and parse one data source. Three kinds:

- ``rss``  — fed into :class:`RSSCollector` via its ``feeds`` dict parameter.
- ``html`` — handled by :class:`GenericHTMLCollector` using the selector rules
  defined here. Requires ``item_selector`` + one of ``link_selector`` /
  ``link_is_item`` to identify products, plus ``title_selector`` (or
  ``title_is_link_text``).
- ``json`` — handled by :class:`GenericJSONCollector`. Reads a JSON list (or a
  nested list via ``items_path``) and pulls ``title_field`` / ``url_field``
  from each element.

Adding a new source = append one :class:`SourceConfig` instance here. No other
code changes needed.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class SourceConfig:
    name: str                          # goes into SourceItem.source (must be unique)
    kind: str                          # "rss" | "html" | "json"
    url: str
    enabled: bool = True

    # --- html-only ---
    item_selector: str | None = None       # repeat-selector for each product/entry
    link_is_item: bool = False             # if True, item_selector returns <a> directly
    title_selector: str | None = None      # sub-selector inside item_selector
    title_is_link_text: bool = False       # if True, title = whole anchor text
    link_selector: str | None = None       # sub-selector for the <a>
    link_attr: str = "href"
    content_selector: str | None = None    # optional short description
    base_url: str | None = None            # for resolving relative hrefs

    # --- json-only ---
    items_path: str | None = None          # dot path; empty / None => root is list
    title_field: str | None = None
    url_field: str | None = None
    url_prefix: str | None = None          # prepended to url_field value
    content_field: str | None = None


SOURCES: list[SourceConfig] = [
    # ===================== RSS feeds (14) =====================
    # --- from user's list (directories with real RSS) ---
    SourceConfig(name="rss:producthunt", kind="rss", url="https://www.producthunt.com/feed"),
    SourceConfig(name="rss:neeed", kind="rss", url="https://neeed.directory/feed.xml"),
    SourceConfig(name="rss:launch_cab", kind="rss", url="https://api.launch.cab/v1/rss/daily"),
    SourceConfig(name="rss:shipstry", kind="rss", url="https://shipstry.com/rss.xml"),
    SourceConfig(name="rss:marketingdb", kind="rss", url="https://marketingdb.live/feed.xml"),

    # --- curated high-signal AI sources ---
    SourceConfig(name="rss:arxiv_cs_ai", kind="rss", url="https://export.arxiv.org/rss/cs.AI"),
    SourceConfig(name="rss:arxiv_cs_lg", kind="rss", url="https://export.arxiv.org/rss/cs.LG"),
    SourceConfig(name="rss:arxiv_cs_cl", kind="rss", url="https://export.arxiv.org/rss/cs.CL"),
    SourceConfig(name="rss:devto_ai", kind="rss", url="https://dev.to/feed/tag/ai"),
    SourceConfig(name="rss:devto_ml", kind="rss", url="https://dev.to/feed/tag/machinelearning"),
    SourceConfig(name="rss:devto_llm", kind="rss", url="https://dev.to/feed/tag/llm"),
    SourceConfig(name="rss:lobsters", kind="rss", url="https://lobste.rs/rss"),
    SourceConfig(name="rss:hackernoon_ai", kind="rss", url="https://hackernoon.com/tagged/ai/feed"),
    SourceConfig(name="rss:smol_ai_news", kind="rss", url="https://buttondown.com/ainews/rss"),

    # --- consumer / lifestyle (added so ideation isn't dev-biased) ---
    # Lifehacker — everyday productivity / life tips
    SourceConfig(name="rss:lifehacker", kind="rss", url="https://lifehacker.com/feed/rss"),
    # Wirecutter — consumer product pain points & wishes. Their /rss/ 500s,
    # /feeds/rss.xml 404s; /feed/ returns 200 and is current.
    SourceConfig(name="rss:wirecutter", kind="rss", url="https://www.nytimes.com/wirecutter/feed/"),
    # Consumer Reports endpoint returns 404 — disabled until a stable feed is found.
    SourceConfig(name="rss:consumer_reports", kind="rss", url="https://www.consumerreports.org/cro/news.xml", enabled=False),
    # The Verge — consumer tech rumors & complaints
    SourceConfig(name="rss:theverge", kind="rss", url="https://www.theverge.com/rss/index.xml"),
    # NYT Well — health, parenting, relationships
    SourceConfig(name="rss:nyt_well", kind="rss", url="https://rss.nytimes.com/services/xml/rss/nyt/Well.xml"),
    # NYT Your Money — personal finance
    SourceConfig(name="rss:nyt_your_money", kind="rss", url="https://rss.nytimes.com/services/xml/rss/nyt/YourMoney.xml"),
    # BBC Life & Style — global consumer perspective
    SourceConfig(name="rss:bbc_life_style", kind="rss", url="https://feeds.bbci.co.uk/news/world/us_and_canada/rss.xml"),
    # The Atlantic — culture / ideas that shape consumer behavior
    SourceConfig(name="rss:atlantic", kind="rss", url="https://www.theatlantic.com/feed/all/"),

    # ===================== HTML scraping (2) =====================
    # fazier.com — SSR homepage lists 50+ launches as /launches/{slug} anchors.
    # Each anchor's text starts with the product name followed by a short tagline.
    SourceConfig(
        name="html:fazier",
        kind="html",
        url="https://fazier.com/",
        item_selector="a[href^='/launches/']",
        link_is_item=True,
        title_is_link_text=True,
        base_url="https://fazier.com",
    ),

    # findly.tools — SSR. Tool detail pages are at /{slug}; homepage lists them
    # as direct anchors with text "{Name} {category} {description}".
    SourceConfig(
        name="html:findly",
        kind="html",
        url="https://findly.tools/",
        item_selector="a[href^='/']:not([href^='/categor']):not([href^='/blog']):not([href^='/submit']):not([href^='/premium']):not([href^='/deals']):not([href^='/product-tour']):not([href^='/contact']):not([href^='/terms']):not([href^='/privacy']):not([href^='/alternatives']):not([href^='/tags']):not([href^='/free-tools']):not([href^='/reviews']):not([href^='/badge'])",
        link_is_item=True,
        title_is_link_text=True,
        base_url="https://findly.tools",
    ),
]
