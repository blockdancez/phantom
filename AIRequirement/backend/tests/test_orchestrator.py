import pytest
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy import select

from app.models import Idea, Document
from app.agent.orchestrator import AgentOrchestrator


@pytest.mark.asyncio
async def test_orchestrator_full_flow(db_session):
    idea = Idea(content="一个在线学习平台")
    db_session.add(idea)
    await db_session.commit()

    mock_researcher = MagicMock()
    mock_researcher.research = AsyncMock(return_value={
        "keywords": ["在线学习"],
        "competitors": [{"title": "Coursera", "url": "https://coursera.org", "summary": "在线课程平台"}],
    })

    mock_writer = MagicMock()
    mock_writer.generate = AsyncMock(return_value={
        "title": "在线学习平台PRD",
        "content": "# 在线学习平台PRD\n\n## 概述\n...",
    })

    orchestrator = AgentOrchestrator(
        db_session=db_session,
        researcher=mock_researcher,
        writer=mock_writer,
    )

    await orchestrator.process(str(idea.id))

    await db_session.refresh(idea)
    assert idea.status == "completed"

    result = await db_session.execute(select(Document).where(Document.idea_id == idea.id))
    doc = result.scalar_one()
    assert doc.title == "在线学习平台PRD"
    assert doc.research["competitors"][0]["title"] == "Coursera"


@pytest.mark.asyncio
async def test_orchestrator_handles_failure(db_session):
    idea = Idea(content="will fail")
    db_session.add(idea)
    await db_session.commit()

    mock_researcher = MagicMock()
    mock_researcher.research = AsyncMock(side_effect=Exception("API error"))

    mock_writer = MagicMock()

    orchestrator = AgentOrchestrator(
        db_session=db_session,
        researcher=mock_researcher,
        writer=mock_writer,
    )

    await orchestrator.process(str(idea.id))

    await db_session.refresh(idea)
    assert idea.status == "failed"
