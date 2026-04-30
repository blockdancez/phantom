import pytest
from unittest.mock import AsyncMock, patch

from src.collectors.generic_html import GenericHTMLCollector
from src.collectors.sources_registry import SourceConfig


SAMPLE_HTML = """
<html><body>
  <div class="card">
    <a href="/launches/one"><h3>Product One</h3> — a cool tool</a>
  </div>
  <div class="card">
    <a href="/launches/two"><h3>Product Two</h3> — another tool</a>
  </div>
  <div class="card">
    <a href="https://external.example.com/three"><h3>Product Three</h3></a>
  </div>
  <!-- dup, should be deduped by url -->
  <div class="card">
    <a href="/launches/one"><h3>Product One</h3> — a cool tool</a>
  </div>
</body></html>
"""


@pytest.mark.asyncio
async def test_generic_html_parses_and_resolves_relative_urls():
    cfg = SourceConfig(
        name="html:test",
        kind="html",
        url="https://example.com/",
        item_selector="a[href^='/launches/'], a[href^='https://external']",
        link_is_item=True,
        title_is_link_text=True,
        base_url="https://example.com",
    )
    collector = GenericHTMLCollector(cfg)
    with patch.object(collector, "_fetch_html", new_callable=AsyncMock, return_value=SAMPLE_HTML):
        items = await collector.collect(limit=10)

    urls = [i["url"] for i in items]
    assert "https://example.com/launches/one" in urls
    assert "https://example.com/launches/two" in urls
    assert "https://external.example.com/three" in urls
    # dedup: even though /launches/one appears twice, result has it once
    assert urls.count("https://example.com/launches/one") == 1
    assert all(i["source"] == "html:test" for i in items)
    assert items[0]["title"].startswith("Product One")


@pytest.mark.asyncio
async def test_generic_html_respects_limit():
    cfg = SourceConfig(
        name="html:test",
        kind="html",
        url="https://example.com/",
        item_selector="a[href^='/launches/'], a[href^='https://external']",
        link_is_item=True,
        title_is_link_text=True,
        base_url="https://example.com",
    )
    collector = GenericHTMLCollector(cfg)
    with patch.object(collector, "_fetch_html", new_callable=AsyncMock, return_value=SAMPLE_HTML):
        items = await collector.collect(limit=2)
    assert len(items) == 2


@pytest.mark.asyncio
async def test_generic_html_returns_empty_on_fetch_failure():
    cfg = SourceConfig(
        name="html:test",
        kind="html",
        url="https://example.com/",
        item_selector="a",
        link_is_item=True,
        title_is_link_text=True,
    )
    collector = GenericHTMLCollector(cfg)
    with patch.object(
        collector, "_fetch_html", new_callable=AsyncMock, side_effect=Exception("boom")
    ):
        items = await collector.collect(limit=10)
    assert items == []


@pytest.mark.asyncio
async def test_generic_html_skips_missing_item_selector():
    cfg = SourceConfig(
        name="html:broken",
        kind="html",
        url="https://example.com/",
        item_selector=None,
    )
    collector = GenericHTMLCollector(cfg)
    with patch.object(collector, "_fetch_html", new_callable=AsyncMock, return_value="<html></html>"):
        items = await collector.collect(limit=10)
    assert items == []


@pytest.mark.asyncio
async def test_generic_html_with_nested_selectors():
    """title_selector + link_selector as sub-selectors inside item_selector."""
    html = """
    <ul>
      <li class="row"><span class="name">Alpha</span><a class="go" href="/a">go</a></li>
      <li class="row"><span class="name">Beta</span><a class="go" href="/b">go</a></li>
    </ul>
    """
    cfg = SourceConfig(
        name="html:nested",
        kind="html",
        url="https://ex.com/",
        item_selector="li.row",
        title_selector=".name",
        link_selector="a.go",
        base_url="https://ex.com",
    )
    collector = GenericHTMLCollector(cfg)
    with patch.object(collector, "_fetch_html", new_callable=AsyncMock, return_value=html):
        items = await collector.collect(limit=10)
    assert [i["title"] for i in items] == ["Alpha", "Beta"]
    assert [i["url"] for i in items] == ["https://ex.com/a", "https://ex.com/b"]
