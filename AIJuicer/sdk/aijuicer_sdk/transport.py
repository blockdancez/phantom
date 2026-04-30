"""HTTP transport：封装对 scheduler /api 的调用。"""

from __future__ import annotations

from typing import Any

import httpx


class SchedulerClient:
    def __init__(self, base_url: str, *, timeout: float = 10.0) -> None:
        self._base = base_url.rstrip("/")
        self._client = httpx.AsyncClient(base_url=self._base, timeout=timeout)

    async def register_agent(
        self, *, name: str, step: str, metadata: dict | None = None
    ) -> dict[str, Any]:
        r = await self._client.post(
            "/api/agents/register",
            json={"name": name, "step": step, "metadata": metadata},
        )
        r.raise_for_status()
        return r.json()

    async def task_start(self, *, task_id: str, agent_id: str, request_id: str) -> dict[str, Any]:
        r = await self._client.put(
            f"/api/tasks/{task_id}/start",
            json={"agent_id": agent_id},
            headers={"X-Request-ID": request_id},
        )
        r.raise_for_status()
        return r.json()

    async def task_complete(self, *, task_id: str, output: dict, request_id: str) -> None:
        r = await self._client.put(
            f"/api/tasks/{task_id}/complete",
            json={"output": output},
            headers={"X-Request-ID": request_id},
        )
        r.raise_for_status()

    async def task_fail(
        self, *, task_id: str, error: str, retryable: bool, request_id: str
    ) -> dict[str, Any]:
        r = await self._client.put(
            f"/api/tasks/{task_id}/fail",
            json={"error": error, "retryable": retryable},
            headers={"X-Request-ID": request_id},
        )
        r.raise_for_status()
        return r.json()

    async def task_heartbeat(self, *, task_id: str, message: str | None, request_id: str) -> None:
        r = await self._client.put(
            f"/api/tasks/{task_id}/heartbeat",
            json={"message": message},
            headers={"X-Request-ID": request_id},
        )
        r.raise_for_status()

    async def agent_heartbeat(
        self, *, agent_id: str, name: str, step: str, metadata: dict | None = None
    ) -> None:
        """续期 agent presence TTL（在线名册由 Redis 持有）。"""
        r = await self._client.post(
            f"/api/agents/{agent_id}/heartbeat",
            json={"name": name, "step": step, "metadata": metadata},
        )
        r.raise_for_status()

    async def create_workflow(
        self,
        *,
        name: str,
        project_name: str,
        input: dict,
        approval_policy: dict | None = None,
        initial_artifacts: list[dict] | None = None,
    ) -> dict[str, Any]:
        """主动创建一条工作流；用于 finder/idea 这种"产生式" agent。

        ``project_name`` 是项目 slug（小写英文 + 短横线），caller 自己生成。
        撞名时 scheduler 会自动加 4 位随机后缀，所以 caller 不必预先查重。
        简单场景可以直接用 ``aijuicer_sdk.slugify_idea`` 从 idea 文本生成。

        如果 producer 已经手里就有完整 idea 产物（无需让 idea agent 再展开一次），
        通过 ``initial_artifacts`` 把它一并传进来——scheduler 落盘并跳过 idea step，
        直接进下一步。条目格式：
            {"step": "idea", "key": "idea.md", "content": "<utf-8 文本>",
             "content_type": "text/markdown"}
        """
        body: dict[str, Any] = {
            "name": name,
            "project_name": project_name,
            "input": input,
            "approval_policy": approval_policy or {},
        }
        if initial_artifacts:
            body["initial_artifacts"] = initial_artifacts
        r = await self._client.post("/api/workflows", json=body)
        r.raise_for_status()
        return r.json()

    async def create_artifact(
        self,
        *,
        workflow_id: str,
        step: str,
        key: str,
        path: str,
        size_bytes: int,
        content_type: str | None,
        sha256: str | None,
        request_id: str,
    ) -> dict[str, Any]:
        """旧版只注册元数据；新代码用 upload_artifact 直接传字节。"""
        r = await self._client.post(
            "/api/artifacts",
            json={
                "workflow_id": workflow_id,
                "step": step,
                "key": key,
                "path": path,
                "size_bytes": size_bytes,
                "content_type": content_type,
                "sha256": sha256,
            },
            headers={"X-Request-ID": request_id},
        )
        r.raise_for_status()
        return r.json()

    async def upload_artifact(
        self,
        *,
        workflow_id: str,
        step: str,
        key: str,
        attempt: int,
        data: bytes,
        content_type: str | None,
        request_id: str,
    ) -> dict[str, Any]:
        """multipart 上传产物字节给 scheduler；scheduler 写进 DB
        （artifacts.content + artifacts.attempt）。每次重跑会以新 attempt 写新行。"""
        files = {"file": (key, data, content_type or "application/octet-stream")}
        form: dict[str, str] = {
            "workflow_id": workflow_id,
            "step": step,
            "key": key,
            "attempt": str(attempt),
        }
        if content_type:
            form["content_type_hint"] = content_type
        r = await self._client.post(
            "/api/artifacts/upload",
            data=form,
            files=files,
            headers={"X-Request-ID": request_id},
        )
        r.raise_for_status()
        return r.json()

    async def fetch_artifact_by_key(self, *, workflow_id: str, step: str, key: str) -> bytes:
        """按 (workflow, step, key) 拿产物字节；用于 ctx.load_artifact。"""
        r = await self._client.get(
            f"/api/workflows/{workflow_id}/artifacts/by-key/content",
            params={"step": step, "key": key},
        )
        if r.status_code == 404:
            raise FileNotFoundError(f"artifact not found: step={step} key={key}")
        r.raise_for_status()
        return r.content

    async def close(self) -> None:
        await self._client.aclose()
