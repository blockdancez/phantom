import pytest
from httpx import AsyncClient, ASGITransport

from app.models import Idea, Document


@pytest.mark.asyncio
async def test_list_documents(app, db_session):
    idea = Idea(content="test idea")
    db_session.add(idea)
    await db_session.commit()

    doc = Document(idea_id=idea.id, title="Test PRD", content="# PRD content")
    db_session.add(doc)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/documents")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 1


@pytest.mark.asyncio
async def test_get_document_by_id(app, db_session):
    idea = Idea(content="another idea")
    db_session.add(idea)
    await db_session.commit()

    doc = Document(idea_id=idea.id, title="PRD", content="# Content")
    db_session.add(doc)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/documents/{doc.id}")

    assert response.status_code == 200
    assert response.json()["title"] == "PRD"


@pytest.mark.asyncio
async def test_get_document_for_idea(app, db_session):
    idea = Idea(content="idea with doc")
    db_session.add(idea)
    await db_session.commit()

    doc = Document(idea_id=idea.id, title="PRD", content="# Content")
    db_session.add(doc)
    await db_session.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get(f"/api/ideas/{idea.id}/document")

    assert response.status_code == 200
    assert response.json()["idea_id"] == str(idea.id)


@pytest.mark.asyncio
async def test_get_document_not_found(app, db_session):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/documents/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404
