import pytest
from unittest.mock import AsyncMock, patch
from src.collectors.twitter_trends import TwitterTrendsCollector


@pytest.mark.asyncio
async def test_twitter_trends_returns_items():
    mock_trends = [
        {"name": "#AIStartups", "url": "https://x.com/search?q=%23AIStartups", "tweet_volume": 50000},
        {"name": "GPT-5", "url": "https://x.com/search?q=GPT-5", "tweet_volume": 120000},
    ]

    collector = TwitterTrendsCollector()
    with patch.object(collector, "_scrape_trends", new_callable=AsyncMock, return_value=mock_trends):
        items = await collector.collect(limit=2)

    assert len(items) == 2
    assert items[0]["source"] == "twitter_trends"
    assert items[0]["title"] == "#AIStartups"
