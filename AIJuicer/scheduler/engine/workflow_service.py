"""Workflow service: 创建/查询/驱动工作流状态转换。"""

from __future__ import annotations

import builtins
import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.engine.state_machine import (
    State,
    next_running_state,
    transition,
)
from scheduler.observability import metrics
from scheduler.observability.logging import get_logger
from scheduler.storage.db import defer_xadd
from scheduler.storage.models import StepExecution, Workflow, WorkflowEvent

logger = get_logger(__name__)


class WorkflowService:
    """所有状态转换在同一 AsyncSession 的事务内完成；调用者负责 commit。"""

    def __init__(self, session: AsyncSession, artifact_root: str | Path) -> None:
        self.session = session
        self.artifact_root = Path(artifact_root)

    async def create(
        self,
        *,
        name: str,
        project_name: str,
        input: dict,
        approval_policy: dict,
        request_id: str,
        initial_artifacts: list[dict] | None = None,
    ) -> uuid.UUID:
        """创建 workflow。

        ``project_name`` 由调用方负责生成（小写英文 + 短横线）；scheduler 只在
        撞名时追加 4 位随机后缀来保证全局唯一。

        默认行为：写入 wf 行 + 转 CREATED → IDEA_RUNNING + 入队 idea 任务，等 agent 处理。

        快捷路径：如果 producer 已经把 idea 产物准备好（`initial_artifacts` 含 step="idea"），
        scheduler 直接落盘那份产物，跳过 IDEA_RUNNING，状态机推到下一步——避免
        producer 自己提交、自己消费的回环。
        """
        import hashlib  # noqa: PLC0415
        from datetime import UTC, datetime  # noqa: PLC0415

        from scheduler.storage.models import Artifact  # noqa: PLC0415

        wf_id = uuid.uuid4()
        wf_artifact_root = str((self.artifact_root / "workflows" / str(wf_id)).resolve())

        project_name = await self._unique_project_name(project_name)

        wf = Workflow(
            id=wf_id,
            name=name,
            project_name=project_name,
            status=State.CREATED.value,
            input=input,
            approval_policy=approval_policy,
            current_step=None,
            artifact_root=wf_artifact_root,
        )
        self.session.add(wf)
        self.session.add(
            WorkflowEvent(
                workflow_id=wf_id,
                event_type="workflow.created",
                payload={"name": name, "project_name": project_name},
                request_id=request_id,
            )
        )
        # 先 flush 让 wf 落盘，否则下面的 Artifact / StepExecution 触发 FK 校验失败
        await self.session.flush()

        # 落盘 initial_artifacts（attempt=1 先写进来）
        idea_prefilled = False
        for art in initial_artifacts or []:
            raw = art["content"].encode("utf-8")
            self.session.add(
                Artifact(
                    workflow_id=wf_id,
                    step=art["step"],
                    key=art["key"],
                    attempt=1,
                    content=raw,
                    size_bytes=len(raw),
                    content_type=art.get("content_type"),
                    sha256=hashlib.sha256(raw).hexdigest(),
                )
            )
            if art["step"] == "idea":
                idea_prefilled = True

        if initial_artifacts:
            await self.session.flush()

        if idea_prefilled:
            # 跳过 idea 的 RUNNING：直接补一条 step_executions(succeeded) +
            # 状态机走 IDEA_RUNNING → IDEA_DONE → next_running_state
            now = datetime.now(UTC)
            self.session.add(
                StepExecution(
                    workflow_id=wf_id,
                    step="idea",
                    attempt=1,
                    status="succeeded",
                    input=input,
                    output={"prefilled": True},
                    request_id=request_id,
                    started_at=now,
                    finished_at=now,
                )
            )
            # 进入 IDEA_RUNNING（状态机要求；只走一瞬，紧接着 advance_on_step_success
            # 把它推到 DONE 并入队下一步）
            wf.status = State.IDEA_RUNNING.value
            wf.current_step = "idea"
            self.session.add(
                WorkflowEvent(
                    workflow_id=wf_id,
                    event_type="state.changed",
                    payload={
                        "from": State.CREATED.value,
                        "to": State.IDEA_RUNNING.value,
                        "via": "initial_artifacts",
                    },
                    request_id=request_id,
                )
            )
            await self.session.flush()
            await self.advance_on_step_success(wf_id, request_id=request_id)
        else:
            await self._advance_to_running(
                wf, target=State.IDEA_RUNNING, request_id=request_id
            )
        return wf_id

    async def get(self, wf_id: uuid.UUID) -> Workflow | None:
        result = await self.session.execute(select(Workflow).where(Workflow.id == wf_id))
        return result.scalar_one_or_none()

    async def _unique_project_name(self, base: str) -> str:
        """挑一个 DB 里没占用的 project_name。base 已占用就挂 `-<4 随机字母>` 直到拿到不冲突的。
        最多重试 10 次（理论不会撞上，4 字母组合空间 26^4 ≈ 45 万）。"""
        from scheduler.engine.project_name import random_suffix  # noqa: PLC0415

        candidate = base
        for _ in range(10):
            exists = (
                await self.session.execute(
                    select(Workflow.id).where(Workflow.project_name == candidate)
                )
            ).first()
            if exists is None:
                return candidate
            candidate = f"{base}-{random_suffix()}"
        # 极小概率，全部撞上：用更长的随机串兜底
        return f"{base}-{random_suffix(8)}"

    async def list(self, *, status: str | None = None, limit: int = 100) -> builtins.list[Workflow]:
        """M1 兼容接口：按 status 精确过滤 + limit。新代码用 list_with_count。"""
        stmt = select(Workflow).order_by(Workflow.created_at.desc()).limit(limit)
        if status:
            stmt = stmt.where(Workflow.status == status)
        result = await self.session.execute(stmt)
        return builtins.list(result.scalars().all())

    async def list_with_count(
        self,
        *,
        q: str | None = None,
        status: str | None = None,
        status_group: str | None = None,
        limit: int = 20,
        offset: int = 0,
    ) -> "tuple[builtins.list[Workflow], int]":  # noqa: UP037 — .list 方法名与内建冲突
        """搜索 + 分组过滤 + 分页，同时返回本次匹配的总数（供前端分页用）。

        status_group 取值：running / awaiting / manual / completed / aborted /
        active（非 terminal）。优先级低于 status 精确匹配。
        """
        from sqlalchemy import func as sa_func  # noqa: PLC0415 — 局部使用避免污染顶层
        from sqlalchemy.sql.elements import ColumnElement  # noqa: PLC0415

        filters: list[ColumnElement[bool]] = []
        if q:
            # 不区分大小写按 name 模糊匹配
            like = f"%{q}%"
            filters.append(Workflow.name.ilike(like))
        if status:
            filters.append(Workflow.status == status)
        elif status_group:
            if status_group == "running":
                filters.append(Workflow.status.like("%\\_RUNNING").op("ESCAPE")("\\"))
            elif status_group == "awaiting":
                filters.append(Workflow.status.like("AWAITING\\_APPROVAL\\_%").op("ESCAPE")("\\"))
            elif status_group == "manual":
                filters.append(Workflow.status == "AWAITING_MANUAL_ACTION")
            elif status_group == "completed":
                filters.append(Workflow.status == "COMPLETED")
            elif status_group == "aborted":
                filters.append(Workflow.status == "ABORTED")
            elif status_group == "active":
                filters.append(~Workflow.status.in_(["COMPLETED", "ABORTED"]))

        base = select(Workflow)
        count_stmt = select(sa_func.count()).select_from(Workflow)
        for f in filters:
            base = base.where(f)
            count_stmt = count_stmt.where(f)

        base = base.order_by(Workflow.created_at.desc()).limit(limit).offset(offset)
        items = builtins.list((await self.session.execute(base)).scalars().all())
        total = int((await self.session.execute(count_stmt)).scalar_one())
        return items, total

    async def advance_on_step_success(self, wf_id: uuid.UUID, *, request_id: str) -> State:
        """Step completed 时被 TaskService 调用：根据 approval_policy 推进。"""
        wf = await self.get(wf_id)
        if wf is None:
            raise ValueError(f"Workflow {wf_id} not found")
        src = State(wf.status)
        # RUNNING -> DONE
        if src.value.endswith("_RUNNING"):
            done = State[src.value.replace("_RUNNING", "_DONE")]
            transition(src, done)
            wf.status = done.value
            self.session.add(
                WorkflowEvent(
                    workflow_id=wf.id,
                    event_type="state.changed",
                    payload={"from": src.value, "to": done.value},
                    request_id=request_id,
                )
            )
            src = done

        target = next_running_state(src, policy=wf.approval_policy)
        transition(src, target)
        wf.status = target.value
        if target.value.endswith("_RUNNING"):
            wf.current_step = target.value.removesuffix("_RUNNING").lower()
        self.session.add(
            WorkflowEvent(
                workflow_id=wf.id,
                event_type="state.changed",
                payload={"from": src.value, "to": target.value},
                request_id=request_id,
            )
        )

        if target.value.endswith("_RUNNING"):
            await self._enqueue_pending_step(
                wf,
                step=target.value.removesuffix("_RUNNING").lower(),
                request_id=request_id,
            )
        elif target == State.COMPLETED:
            metrics.workflows_total.labels(status="COMPLETED").inc()
        return target

    async def _advance_to_running(self, wf: Workflow, *, target: State, request_id: str) -> None:
        src = State(wf.status)
        transition(src, target)
        wf.status = target.value
        wf.current_step = target.value.removesuffix("_RUNNING").lower()
        self.session.add(
            WorkflowEvent(
                workflow_id=wf.id,
                event_type="state.changed",
                payload={"from": src.value, "to": target.value},
                request_id=request_id,
            )
        )
        await self._enqueue_pending_step(
            wf,
            step=target.value.removesuffix("_RUNNING").lower(),
            request_id=request_id,
        )

    async def _enqueue_pending_step(
        self, wf: Workflow, *, step: str, request_id: str
    ) -> StepExecution:
        """插入 pending step_execution，并登记 commit 后向 Redis Streams XADD。

        派发前会检查该 step 是否有在线 Agent；没有则记 warning + 计数器，
        但仍正常 XADD（Redis Stream 自带缓冲，Agent 上线后会消费历史消息）。
        """
        result = await self.session.execute(
            select(StepExecution)
            .where(StepExecution.workflow_id == wf.id)
            .where(StepExecution.step == step)
        )
        existing = list(result.scalars().all())
        attempt = max((e.attempt for e in existing), default=0) + 1

        exec_ = StepExecution(
            workflow_id=wf.id,
            step=step,
            attempt=attempt,
            status="pending",
            input=wf.input,
            request_id=request_id,
        )
        self.session.add(exec_)
        self.session.add(
            WorkflowEvent(
                workflow_id=wf.id,
                event_type="task.enqueued",
                payload={
                    "step": step,
                    "attempt": attempt,
                    "task_id": str(exec_.id),
                },
                request_id=request_id,
            )
        )
        await self.session.flush()
        logger.info(
            "任务已入库待派发",
            workflow_id=str(wf.id),
            step=step,
            attempt=attempt,
            task_id=str(exec_.id),
        )
        await self._warn_if_no_online_agent(step=step, workflow_id=str(wf.id))
        defer_xadd(
            self.session,
            step=step,
            payload={
                "task_id": str(exec_.id),
                "workflow_id": str(wf.id),
                "project_name": wf.project_name,
                "step": step,
                "attempt": attempt,
                "input": wf.input,
                "artifact_root": wf.artifact_root,
                "request_id": request_id,
            },
        )
        return exec_

    async def _warn_if_no_online_agent(self, *, step: str, workflow_id: str) -> None:
        """派发前预检：该 step 没有任何在线 Agent 时打 warning + 计数器。

        Redis 不可用 / 测试环境（InMemoryTaskQueue）下静默跳过。
        """
        from scheduler.api import get_database  # noqa: PLC0415 — 避免循环依赖
        from scheduler.storage.agent_presence import has_online_for_step  # noqa: PLC0415
        from scheduler.storage.redis_queue import RedisTaskQueue  # noqa: PLC0415

        try:
            db = get_database()
        except RuntimeError:
            return  # 测试或未初始化 — 直接放行
        tq = db.task_queue
        if not isinstance(tq, RedisTaskQueue):
            return
        try:
            online = await has_online_for_step(tq.client, step=step)
        except Exception as e:  # noqa: BLE001 — 预检失败不应阻塞派发
            logger.warning("派发前在线 Agent 预检失败", step=step, error=str(e))
            return
        if not online:
            metrics.dispatch_no_online_total.labels(step=step).inc()
            logger.warning(
                "无在线 Agent，任务将滞留在 Stream 中等待消费",
                step=step,
                workflow_id=workflow_id,
            )
