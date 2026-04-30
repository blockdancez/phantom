import pytest
from unittest.mock import AsyncMock, patch
from src.collectors.hackernews import HackerNewsCollector


@pytest.mark.asyncio
async def test_hackernews_collector_returns_items():
    mock_top_stories = [1, 2, 3]
    mock_item = {
        "id": 1,
        "title": "Show HN: AI-powered idea finder",
        "url": "https://example.com/article",
        "score": 150,
        "by": "testuser",
        "time": 1700000000,
        "descendants": 42,
        "type": "story",
    }

    collector = HackerNewsCollector()

    with patch.object(collector, "_fetch_json", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = [mock_top_stories, mock_item, mock_item, mock_item]
        items = await collector.collect(limit=3)

    assert len(items) == 3
    assert items[0]["title"] == "Show HN: AI-powered idea finder"
    assert items[0]["source"] == "hackernews"
    assert items[0]["url"] == "https://example.com/article"


@pytest.mark.asyncio
async def test_hackernews_collector_fetches_content():
    mock_top_stories = [1]
    mock_item = {
        "id": 1,
        "title": "Test Article",
        "url": "https://example.com/test",
        "score": 100,
        "by": "user",
        "time": 1700000000,
        "descendants": 10,
        "type": "story",
        "text": "This is the article body text from HN.",
    }

    collector = HackerNewsCollector()

    with patch.object(collector, "_fetch_json", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.side_effect = [mock_top_stories, mock_item]
        items = await collector.collect(limit=1)

    assert items[0]["content"] != ""
