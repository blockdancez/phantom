import pytest
from unittest.mock import AsyncMock, patch

from app.agent.researcher import Researcher


@pytest.mark.asyncio
async def test_researcher_extracts_keywords():
    researcher = Researcher(tavily_api_key="tvly-test")
    keywords = researcher.extract_keywords("一个帮助大学生管理课程和作业的移动应用")
    assert len(keywords) > 0
    assert isinstance(keywords, list)


@pytest.mark.asyncio
async def test_researcher_search_competitors():
    mock_response = {
        "results": [
            {
                "title": "Todoist - 任务管理",
                "url": "https://todoist.com",
                "content": "Todoist是一款流行的任务管理应用...",
            },
            {
                "title": "Notion - 笔记和项目管理",
                "url": "https://notion.so",
                "content": "Notion是一款全能的工作空间工具...",
            },
        ]
    }

    researcher = Researcher(tavily_api_key="tvly-test")

    with patch.object(researcher, "_search", new_callable=AsyncMock, return_value=mock_response["results"]):
        results = await researcher.research("一个帮助大学生管理课程和作业的移动应用")

    assert "competitors" in results
    assert len(results["competitors"]) == 2
    assert results["competitors"][0]["title"] == "Todoist - 任务管理"


@pytest.mark.asyncio
async def test_researcher_handles_empty_results():
    researcher = Researcher(tavily_api_key="tvly-test")

    with patch.object(researcher, "_search", new_callable=AsyncMock, return_value=[]):
        results = await researcher.research("一个非常独特的无竞品产品")

    assert "competitors" in results
    assert len(results["competitors"]) == 0
