import pytest
from unittest.mock import AsyncMock, patch

from src.collectors.generic_json import GenericJSONCollector
from src.collectors.sources_registry import SourceConfig


@pytest.mark.asyncio
async def test_generic_json_root_list():
    data = [
        {"id": "alpha", "name": "Alpha", "desc": "first"},
        {"id": "beta", "name": "Beta", "desc": "second"},
    ]
    cfg = SourceConfig(
        name="json:root",
        kind="json",
        url="https://api.ex.com/",
        title_field="name",
        url_field="id",
        url_prefix="https://ex.com",
        content_field="desc",
    )
    collector = GenericJSONCollector(cfg)
    with patch.object(collector, "_fetch_json", new_callable=AsyncMock, return_value=data):
        items = await collector.collect(limit=10)
    assert len(items) == 2
    assert items[0]["title"] == "Alpha"
    assert items[0]["url"] == "https://ex.com/alpha"
    assert items[0]["content"] == "first"
    assert all(i["source"] == "json:root" for i in items)


@pytest.mark.asyncio
async def test_generic_json_nested_path():
    data = {"result": {"items": [{"title": "X", "link": "https://x.com"}]}}
    cfg = SourceConfig(
        name="json:nested",
        kind="json",
        url="https://api.ex.com/",
        items_path="result.items",
        title_field="title",
        url_field="link",
    )
    collector = GenericJSONCollector(cfg)
    with patch.object(collector, "_fetch_json", new_callable=AsyncMock, return_value=data):
        items = await collector.collect(limit=10)
    assert len(items) == 1
    assert items[0]["url"] == "https://x.com"


@pytest.mark.asyncio
async def test_generic_json_dedupes_and_respects_limit():
    data = [
        {"n": "A", "u": "https://ex.com/1"},
        {"n": "A dup", "u": "https://ex.com/1"},  # same url → skipped
        {"n": "B", "u": "https://ex.com/2"},
        {"n": "C", "u": "https://ex.com/3"},
    ]
    cfg = SourceConfig(
        name="json:dedup",
        kind="json",
        url="https://api.ex.com/",
        title_field="n",
        url_field="u",
    )
    collector = GenericJSONCollector(cfg)
    with patch.object(collector, "_fetch_json", new_callable=AsyncMock, return_value=data):
        items = await collector.collect(limit=2)
    assert len(items) == 2
    assert [i["url"] for i in items] == ["https://ex.com/1", "https://ex.com/2"]


@pytest.mark.asyncio
async def test_generic_json_returns_empty_on_fetch_failure():
    cfg = SourceConfig(
        name="json:broken",
        kind="json",
        url="https://api.ex.com/",
        title_field="t",
        url_field="u",
    )
    collector = GenericJSONCollector(cfg)
    with patch.object(
        collector, "_fetch_json", new_callable=AsyncMock, side_effect=Exception("boom")
    ):
        items = await collector.collect(limit=10)
    assert items == []


@pytest.mark.asyncio
async def test_generic_json_skips_when_missing_required_fields():
    cfg = SourceConfig(name="json:bad", kind="json", url="https://x")
    collector = GenericJSONCollector(cfg)
    with patch.object(collector, "_fetch_json", new_callable=AsyncMock, return_value=[{"a": 1}]):
        items = await collector.collect(limit=10)
    assert items == []
