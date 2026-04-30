"""API 端到端集成测试。"""

from __future__ import annotations

from collections.abc import AsyncIterator

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

from scheduler.api import set_database
from scheduler.main import create_app
from scheduler.storage.db import Database
from scheduler.storage.models import StepExecution


@pytest_asyncio.fixture
async def client(database: Database) -> AsyncIterator[AsyncClient]:
    set_database(database)
    app = create_app()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as c:
        yield c


@pytest.mark.asyncio
async def test_health(client: AsyncClient) -> None:
    r = await client.get("/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


@pytest.mark.asyncio
async def test_create_workflow_returns_finder_running(client: AsyncClient) -> None:
    r = await client.post(
        "/api/workflows",
        json={
            "name": "wf1",
            "project_name": "wf1",
            "input": {"topic": "x"},
            "approval_policy": {},
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "IDEA_RUNNING"
    assert body["current_step"] == "idea"


@pytest.mark.asyncio
async def test_full_step_lifecycle_through_api(client: AsyncClient, database: Database) -> None:
    """端到端：create workflow → agent 接管 → start/complete → 自动推进到下一步。"""
    # 1) create
    r = await client.post(
        "/api/workflows",
        json={
            "name": "t",
            "project_name": "t",
            "input": {"topic": "x"},
            "approval_policy": {"requirement": "auto"},
        },
    )
    assert r.status_code == 201
    wf_id = r.json()["id"]

    # 2) agent register
    r = await client.post("/api/agents/register", json={"name": "ai-finder-01", "step": "idea"})
    assert r.status_code == 200

    # 3) 直接查 DB 拿 pending finder task_id
    async with database.session() as s:
        task_id = (
            await s.execute(
                select(StepExecution.id)
                .where(StepExecution.workflow_id == wf_id)
                .where(StepExecution.step == "idea")
            )
        ).scalar_one()

    # 4) task start
    r = await client.put(f"/api/tasks/{task_id}/start", json={"agent_id": "ai-finder-01"})
    assert r.status_code == 200

    # 5) task complete → 应 auto 推进到 REQUIREMENT_RUNNING
    r = await client.put(f"/api/tasks/{task_id}/complete", json={"output": {"idea_summary": "s"}})
    assert r.status_code == 200

    r = await client.get(f"/api/workflows/{wf_id}")
    assert r.json()["status"] == "REQUIREMENT_RUNNING"
    assert r.json()["current_step"] == "requirement"

    # 6) DB 应有 requirement 的 pending task_execution
    async with database.session() as s:
        req_tasks = (
            (
                await s.execute(
                    select(StepExecution)
                    .where(StepExecution.workflow_id == wf_id)
                    .where(StepExecution.step == "requirement")
                )
            )
            .scalars()
            .all()
        )
        assert len(req_tasks) == 1
        assert req_tasks[0].status == "pending"


@pytest.mark.asyncio
async def test_request_id_echoed_in_response_header(client: AsyncClient) -> None:
    r = await client.post(
        "/api/workflows",
        json={"name": "r", "project_name": "r", "input": {}, "approval_policy": {}},
        headers={"X-Request-ID": "req_custom"},
    )
    assert r.headers.get("X-Request-ID") == "req_custom"


@pytest.mark.asyncio
async def test_list_workflows_filter_by_status(client: AsyncClient) -> None:
    await client.post(
        "/api/workflows",
        json={"name": "a", "project_name": "a", "input": {}, "approval_policy": {}},
    )
    await client.post(
        "/api/workflows",
        json={"name": "b", "project_name": "b", "input": {}, "approval_policy": {}},
    )
    r = await client.get("/api/workflows?status=IDEA_RUNNING&page_size=10")
    assert r.status_code == 200
    body = r.json()
    assert body["page"] == 1
    assert body["page_size"] == 10
    assert body["total"] >= 2
    assert all(i["status"] == "IDEA_RUNNING" for i in body["items"])


@pytest.mark.asyncio
async def test_list_workflows_search_and_paging(client: AsyncClient) -> None:
    """q 模糊搜索 + 分组过滤 + 分页契约。"""
    import uuid as _uuid

    # 共享远程 DB 上测试会累积；用 per-run 唯一前缀避免跨次污染
    uniq = f"zyx-search-{_uuid.uuid4().hex[:8]}"
    for i in range(3):
        await client.post(
            "/api/workflows",
            json={
                "name": f"{uniq}-{i}",
                "project_name": f"{uniq}-{i}",
                "input": {},
                "approval_policy": {},
            },
        )
    # 模糊搜索
    r = await client.get(f"/api/workflows?q={uniq}&page_size=2")
    body = r.json()
    assert body["total"] == 3
    assert body["page_size"] == 2
    assert len(body["items"]) == 2
    # 第二页
    r2 = await client.get(f"/api/workflows?q={uniq}&page_size=2&page=2")
    body2 = r2.json()
    assert body2["page"] == 2
    assert len(body2["items"]) == 1
    # 分组筛选（active = 非 terminal）
    r3 = await client.get(f"/api/workflows?q={uniq}&status_group=active")
    assert r3.json()["total"] >= 3


@pytest.mark.asyncio
async def test_approve_invalid_state_returns_409(client: AsyncClient) -> None:
    r = await client.post(
        "/api/workflows",
        json={"name": "r", "project_name": "r", "input": {}, "approval_policy": {}},
    )
    wf_id = r.json()["id"]
    # workflow 在 IDEA_RUNNING 状态，无法直接 approve requirement
    r = await client.post(
        f"/api/workflows/{wf_id}/approvals",
        json={"decision": "approve", "step": "requirement"},
    )
    assert r.status_code == 409
