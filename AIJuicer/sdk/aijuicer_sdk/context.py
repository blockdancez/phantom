"""AgentContext：handler 内可用的副作用对象。

产物存取**全部走 HTTP**（不再依赖 agent 与 scheduler 共享 FS）：
- save_artifact → POST /api/artifacts/upload （multipart 字节）
- load_artifact → GET  /api/workflows/{wf}/artifacts/by-key/content
两端可以分布在不同机器、不同容器、不同云。
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from typing import Any

import structlog

from aijuicer_sdk.transport import SchedulerClient


@dataclass
class ArtifactRef:
    """save_artifact 的返回值。"""

    key: str
    """保存时传入的 key（如 ``idea.md``）。"""
    size_bytes: int
    """字节数。"""
    sha256: str
    """内容 sha256。"""


class AgentContext:
    """handler 收到的第二个参数（实际上是第一个；task payload 是第二个）。

    ===== 字段（只读，由 SDK 注入） =====
    task_id      : str   该次执行的 UUID = step_executions.id
    workflow_id  : str   工作流 UUID
    project_name : str   项目 slug（小写英文 + 短横线，全局唯一）。
                         用作代码仓库目录 / 数据库名 / 项目文件夹命名等。
    step         : str   6 步之一 (idea / requirement / plan / design / devtest / deploy)
    attempt      : int   第几次重试。1 = 首跑；> 1 = 重跑
    input        : dict  workflow.input。常见字段：
                         - text                       原始用户输入
                         - user_feedback[<step>]      该 step 的最新重跑指令
    request_id   : str   链路追踪 id
    raw_payload  : dict  scheduler 派发的原始 task payload（含上面所有字段）。
                         一般用不到；只有想做"自定义字段透传"时才直接读它。
    artifact_root: str   legacy（共享 FS 模式下的目录路径）；HTTP 模式不用
    log          : structlog logger，已绑定上面所有字段，调用 .ainfo / .awarning 即可

    ===== 方法 =====
    await ctx.heartbeat(message=None)
        手动汇报一次任务级心跳。SDK 自动每 heartbeat_interval 秒（默认 30s）
        汇报一次；这里调用是用来上报"当前进度文字"。

    await ctx.save_artifact(key, data, content_type=None) -> ArtifactRef
        上传产物字节给 scheduler。data 可以是 str 或 bytes；str 会按 utf-8 编码。
        scheduler 把字节存进 Postgres `artifacts.content` 列，用 sha256 + (wf,
        step, key, attempt) 唯一约束。返回的 ArtifactRef 含 size 和 sha256。

    await ctx.load_artifact(step, key) -> bytes
        从 scheduler 拉某个 (workflow, step, key) 的最新 attempt 字节。
        找不到时抛 FileNotFoundError。可读其他 step 的产物（跨步骤上下文）。
    """

    def __init__(
        self,
        *,
        task_id: str,
        workflow_id: str,
        project_name: str,
        step: str,
        attempt: int,
        input: dict,
        artifact_root: str,  # 兼容旧 payload；HTTP 模式下 SDK 不再使用
        request_id: str,
        raw_payload: dict[str, Any],
        client: SchedulerClient,
    ) -> None:
        self.task_id = task_id
        self.workflow_id = workflow_id
        self.project_name = project_name
        self.step = step
        self.attempt = attempt
        self.input = input
        self.artifact_root = artifact_root
        self.request_id = request_id
        self.raw_payload = raw_payload
        self._client = client
        self.log = structlog.get_logger("aijuicer_sdk.handler").bind(
            request_id=request_id,
            workflow_id=workflow_id,
            project_name=project_name,
            step=step,
            attempt=attempt,
            task_id=task_id,
        )

    async def heartbeat(self, message: str | None = None) -> None:
        await self._client.task_heartbeat(
            task_id=self.task_id, message=message, request_id=self.request_id
        )

    async def save_artifact(
        self, key: str, data: str | bytes, *, content_type: str | None = None
    ) -> ArtifactRef:
        """把产物字节通过 HTTP 上传给 scheduler，由 scheduler 写入 DB。
        当前 attempt（来自 task payload）会一起带上，scheduler 据此区分每次重跑的输出。
        """
        raw: bytes = data.encode("utf-8") if isinstance(data, str) else data
        await self._client.upload_artifact(
            workflow_id=self.workflow_id,
            step=self.step,
            key=key,
            attempt=self.attempt,
            data=raw,
            content_type=content_type,
            request_id=self.request_id,
        )
        ref = ArtifactRef(
            key=key,
            size_bytes=len(raw),
            sha256=hashlib.sha256(raw).hexdigest(),
        )
        await self.log.ainfo(
            "产物保存成功", key=key, size_bytes=ref.size_bytes, sha256=ref.sha256
        )
        return ref

    async def load_artifact(self, step: str, key: str) -> bytes:
        """从 scheduler 拉指定 step+key 的产物字节。

        找不到时抛 FileNotFoundError（保持与旧 FS 版一致的错误类型）。
        """
        return await self._client.fetch_artifact_by_key(
            workflow_id=self.workflow_id, step=step, key=key
        )

    @staticmethod
    def from_task_payload(payload: dict[str, Any], *, client: SchedulerClient) -> AgentContext:
        return AgentContext(
            task_id=payload["task_id"],
            workflow_id=payload["workflow_id"],
            project_name=payload.get("project_name") or "",
            step=payload["step"],
            attempt=int(payload["attempt"]),
            input=payload.get("input") or {},
            artifact_root=payload.get("artifact_root", ""),
            request_id=payload["request_id"],
            raw_payload=payload,
            client=client,
        )
