import pytest
from unittest.mock import AsyncMock, patch
from src.collectors.rss_collector import RSSCollector


@pytest.mark.asyncio
async def test_rss_collector_parses_feed():
    mock_feed_xml = """<?xml version="1.0"?>
    <rss version="2.0">
      <channel>
        <title>Test Feed</title>
        <item>
          <title>AI Revolution in 2026</title>
          <link>https://example.com/ai-revolution</link>
          <description>Full article about the AI revolution and its impact.</description>
          <pubDate>Mon, 14 Apr 2026 10:00:00 GMT</pubDate>
        </item>
        <item>
          <title>New SaaS Trends</title>
          <link>https://example.com/saas-trends</link>
          <description>SaaS trends for the coming year.</description>
          <pubDate>Mon, 14 Apr 2026 09:00:00 GMT</pubDate>
        </item>
      </channel>
    </rss>"""

    collector = RSSCollector(feeds={
        "techcrunch": "https://feeds.example.com/tc",
    })

    with patch.object(collector, "_fetch_html", new_callable=AsyncMock, return_value=mock_feed_xml):
        items = await collector.collect(limit=10)

    assert len(items) == 2
    assert items[0]["source"] == "rss:techcrunch"
    assert items[0]["title"] == "AI Revolution in 2026"
    assert "AI revolution" in items[0]["content"]


@pytest.mark.asyncio
async def test_rss_collector_respects_limit():
    mock_feed_xml = """<?xml version="1.0"?>
    <rss version="2.0"><channel><title>T</title>
      <item><title>A</title><link>https://a.com/1</link><description>D1</description></item>
      <item><title>B</title><link>https://a.com/2</link><description>D2</description></item>
      <item><title>C</title><link>https://a.com/3</link><description>D3</description></item>
    </channel></rss>"""

    collector = RSSCollector(feeds={"test": "https://feeds.example.com/t"})
    with patch.object(collector, "_fetch_html", new_callable=AsyncMock, return_value=mock_feed_xml):
        items = await collector.collect(limit=2)

    assert len(items) == 2
