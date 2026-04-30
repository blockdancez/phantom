import pytest
from unittest.mock import AsyncMock, MagicMock
from src.collectors.ingester import ingest_items


@pytest.mark.asyncio
async def test_ingest_items_creates_records():
    raw_items = [
        {
            "source": "hackernews",
            "title": "Test Article",
            "url": "https://example.com/unique-1",
            "content": "Some content",
            "raw_data": {"id": 1},
            "collected_at": "2026-04-14T10:00:00+00:00",
        },
    ]

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=None)))

    count = await ingest_items(mock_session, raw_items)
    assert count == 1
    mock_session.add.assert_called_once()
    mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_ingest_items_skips_duplicates():
    raw_items = [
        {
            "source": "hackernews",
            "title": "Existing",
            "url": "https://example.com/exists",
            "content": "Old",
            "raw_data": {},
            "collected_at": "2026-04-14T10:00:00+00:00",
        },
    ]

    mock_existing = MagicMock()
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=MagicMock(scalar_one_or_none=MagicMock(return_value=mock_existing)))

    count = await ingest_items(mock_session, raw_items)
    assert count == 0
    mock_session.add.assert_not_called()
