import pytest
from httpx import AsyncClient, ASGITransport


@pytest.mark.asyncio
async def test_create_idea(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post(
            "/api/ideas",
            json={"content": "一个AI驱动的代码审查工具"},
        )

    assert response.status_code == 201
    body = response.json()
    assert body["content"] == "一个AI驱动的代码审查工具"
    assert body["status"] == "pending"
    assert "id" in body


@pytest.mark.asyncio
async def test_list_ideas(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/api/ideas", json={"content": "idea 1"})
        await client.post("/api/ideas", json={"content": "idea 2"})

        response = await client.get("/api/ideas")

    assert response.status_code == 200
    body = response.json()
    assert body["total"] >= 2
    assert len(body["ideas"]) >= 2


@pytest.mark.asyncio
async def test_get_idea_by_id(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        create_resp = await client.post("/api/ideas", json={"content": "test idea"})
        idea_id = create_resp.json()["id"]

        response = await client.get(f"/api/ideas/{idea_id}")

    assert response.status_code == 200
    assert response.json()["id"] == idea_id


@pytest.mark.asyncio
async def test_get_idea_not_found(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.get("/api/ideas/00000000-0000-0000-0000-000000000000")

    assert response.status_code == 404


@pytest.mark.asyncio
async def test_create_idea_empty_content(app):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/ideas", json={"content": ""})

    assert response.status_code == 422
