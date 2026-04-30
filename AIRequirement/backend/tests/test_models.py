import pytest
from sqlalchemy import select

from app.models import Idea, Document


@pytest.mark.asyncio
async def test_create_idea(db_session):
    idea = Idea(content="一个帮助人们学习编程的AI助手")
    db_session.add(idea)
    await db_session.commit()

    result = await db_session.execute(select(Idea).where(Idea.content == "一个帮助人们学习编程的AI助手"))
    saved = result.scalar_one()

    assert saved.id is not None
    assert saved.content == "一个帮助人们学习编程的AI助手"
    assert saved.status == "pending"
    assert saved.created_at is not None


@pytest.mark.asyncio
async def test_create_document_linked_to_idea(db_session):
    idea = Idea(content="在线教育平台")
    db_session.add(idea)
    await db_session.commit()

    doc = Document(
        idea_id=idea.id,
        title="在线教育平台产品需求文档",
        content="# PRD\n\n## 概述\n...",
        research={"competitors": ["Coursera", "Udemy"]},
    )
    db_session.add(doc)
    await db_session.commit()

    result = await db_session.execute(select(Document).where(Document.idea_id == idea.id))
    saved = result.scalar_one()

    assert saved.title == "在线教育平台产品需求文档"
    assert saved.research["competitors"] == ["Coursera", "Udemy"]
    assert saved.idea_id == idea.id
