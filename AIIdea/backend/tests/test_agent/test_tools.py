import sys

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

# src.agent.tools.__init__ re-exports the tool function under the same name
# as the submodule, shadowing the module attribute. Grab the module from
# sys.modules so we can monkeypatch the session factory it uses.
search_module = sys.modules["src.agent.tools.search_items"]
from src.agent.tools.search_items import search_items  # noqa: E402
from src.agent.tools.trend_synthesizer import synthesize_trends  # noqa: E402


@pytest.mark.asyncio
async def test_search_items_returns_results(monkeypatch: pytest.MonkeyPatch):
    mock_items = [
        MagicMock(
            title="AI Tool X",
            source="hackernews",
            content="A tool that does X",
            category="AI/ML",
            score=8.5,
            tags=["ai", "tools"],
            url="https://example.com/1",
            id="test-uuid-1",
        ),
    ]
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = mock_items

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    class _Ctx:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        search_module, "get_async_session_factory", lambda: (lambda: _Ctx())
    )

    result = await search_items.ainvoke(
        {"query": "AI tools", "category": "AI/ML", "min_score": 7.0},
    )

    assert "AI Tool X" in result


@pytest.mark.asyncio
async def test_search_items_no_matches(monkeypatch: pytest.MonkeyPatch):
    mock_result = MagicMock()
    mock_result.scalars.return_value.all.return_value = []
    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)

    class _Ctx:
        async def __aenter__(self):
            return mock_session

        async def __aexit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(
        search_module, "get_async_session_factory", lambda: (lambda: _Ctx())
    )
    result = await search_items.ainvoke({"query": "nope"})
    assert "No items found" in result


@pytest.mark.asyncio
async def test_synthesize_trends_returns_analysis():
    mock_response = (
        "Top trends: AI-powered developer tools are surging with 3 related items across sources."
    )

    with patch("src.agent.tools.trend_synthesizer.ChatOpenAI") as MockLLM:
        instance = MockLLM.return_value
        instance.ainvoke = AsyncMock(return_value=MagicMock(content=mock_response))

        result = await synthesize_trends.ainvoke(
            {"items_summary": "Item 1: AI tool\nItem 2: Code review"},
        )

    assert "trends" in result.lower() or "AI" in result
