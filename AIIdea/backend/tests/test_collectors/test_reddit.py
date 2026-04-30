import pytest
from unittest.mock import AsyncMock, patch

from src.collectors.reddit import RedditCollector

# Minimal Atom feed with a single entry that feedparser will accept.
SAMPLE_FEED = """<?xml version='1.0' encoding='utf-8'?>
<feed xmlns='http://www.w3.org/2005/Atom'>
  <title>r/tech</title>
  <entry>
    <title>New AI tool released</title>
    <link href='https://reddit.com/r/tech/abc/new_ai_tool/'/>
    <summary type='html'><![CDATA[<p>This new AI tool is amazing.</p>]]></summary>
    <author><name>/u/example</name></author>
    <published>2025-04-23T10:00:00+00:00</published>
  </entry>
</feed>
"""


@pytest.mark.asyncio
async def test_reddit_collector_parses_single_entry():
    collector = RedditCollector(subreddits=["tech"])
    with patch.object(
        collector,
        "_fetch_html",
        new_callable=AsyncMock,
        return_value=SAMPLE_FEED,
    ):
        items = await collector.collect(limit=1)
    await collector.close()

    assert len(items) == 1
    item = items[0]
    assert item["source"] == "reddit:tech"
    assert item["title"] == "New AI tool released"
    assert item["url"] == "https://reddit.com/r/tech/abc/new_ai_tool/"
    assert "AI tool is amazing" in item["content"]


@pytest.mark.asyncio
async def test_reddit_collector_skips_on_fetch_failure():
    collector = RedditCollector(subreddits=["tech", "ai"])

    async def fake_fetch(url: str) -> str:
        if "ai" in url:
            raise RuntimeError("network down")
        return SAMPLE_FEED

    with patch.object(collector, "_fetch_html", side_effect=fake_fetch):
        items = await collector.collect(limit=1)
    await collector.close()

    assert len(items) == 1
    assert items[0]["source"] == "reddit:tech"


@pytest.mark.asyncio
async def test_reddit_collector_empty_feed_yields_nothing():
    empty_feed = "<?xml version='1.0'?><feed xmlns='http://www.w3.org/2005/Atom'/>"
    collector = RedditCollector(subreddits=["tech"])
    with patch.object(
        collector,
        "_fetch_html",
        new_callable=AsyncMock,
        return_value=empty_feed,
    ):
        items = await collector.collect(limit=5)
    await collector.close()
    assert items == []
