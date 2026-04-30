"""/api/artifacts endpoints：上传/下载产物 + UI 列表 / 预览。

设计：scheduler 是产物存储的唯一权威——agent 通过 HTTP 上传字节，scheduler 写到自己
的本地盘（路径来自 wf.artifact_root），统一对外提供 /api/artifacts/{id}/content。
这样 agent 与 scheduler 不需要共享文件系统，可以跑在不同机器上。

向后兼容：保留 `POST /api/artifacts`（仅写元数据）给共享 FS 部署，但新代码应该用
`POST /api/artifacts/upload`（带 multipart 文件体）。
"""

from __future__ import annotations

import hashlib
import mimetypes
import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse, Response
from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.api import get_session
from scheduler.api.schemas import ArtifactCreate, ArtifactEditRequest, ArtifactRead
from scheduler.observability.logging import get_logger, get_request_id
from scheduler.storage.models import Artifact, Workflow, WorkflowEvent

logger = get_logger(__name__)
router = APIRouter(prefix="/api", tags=["artifacts"])

# 文本型 MIME 列表：前端可以直接内嵌渲染
_TEXT_CONTENT_TYPES = {
    "text/plain",
    "text/markdown",
    "text/html",
    "text/css",
    "text/javascript",
    "application/json",
    "application/xml",
    "application/yaml",
    "application/x-yaml",
    "image/svg+xml",
}


def _infer_content_type(path: str, explicit: str | None) -> str:
    if explicit:
        return explicit
    guess, _ = mimetypes.guess_type(path)
    return guess or "application/octet-stream"




@router.post("/artifacts", response_model=ArtifactRead, status_code=201)
async def create_artifact(
    body: ArtifactCreate,
    session: AsyncSession = Depends(get_session),
) -> ArtifactRead:
    """旧版接口：仅注册元数据（path 指向共享 FS 上的真实文件）。
    新代码请用 POST /api/artifacts/upload 走 multipart 上传字节。
    """
    stmt = (
        pg_insert(Artifact)
        .values(
            id=uuid.uuid4(),
            workflow_id=body.workflow_id,
            step=body.step,
            key=body.key,
            path=body.path,
            size_bytes=body.size_bytes,
            content_type=_infer_content_type(body.key, body.content_type),
            sha256=body.sha256,
        )
        .on_conflict_do_update(
            constraint="uq_artifact_key",
            set_={
                "path": body.path,
                "size_bytes": body.size_bytes,
                "sha256": body.sha256,
            },
        )
        .returning(Artifact)
    )
    result = await session.execute(stmt)
    art = result.scalar_one()
    logger.info(
        "登记产物元数据",
        workflow_id=str(body.workflow_id),
        step=body.step,
        key=body.key,
        size_bytes=body.size_bytes,
        request_id=get_request_id() or "req_unknown",
    )
    return ArtifactRead.model_validate(art)


@router.post("/artifacts/upload", response_model=ArtifactRead, status_code=201)
async def upload_artifact(
    workflow_id: uuid.UUID = Form(...),
    step: str = Form(...),
    key: str = Form(...),
    attempt: int = Form(1),
    content_type_hint: str | None = Form(None),
    file: UploadFile = File(...),
    session: AsyncSession = Depends(get_session),
) -> ArtifactRead:
    """multipart 上传：scheduler 把字节存进 DB（artifacts.content）。

    每次 agent 重跑都会以一个新 attempt 写入新行；详情页"产物对比"面板拿
    最小 attempt 作"首次输出"、最大 attempt 作"上次输出"。
    幂等性：同 (workflow_id, step, key, attempt) 多次 upload 走 UPSERT
    （handler 内部重试 / 网络抖动场景下覆盖同一行而不是新增）。
    """
    wf = (
        await session.execute(select(Workflow).where(Workflow.id == workflow_id))
    ).scalar_one_or_none()
    if wf is None:
        raise HTTPException(404, "Workflow not found")

    # 流式读到内存计算 sha256（产物通常 < 几 MB；超大文件未来上 S3）
    h = hashlib.sha256()
    chunks: list[bytes] = []
    size = 0
    while chunk := await file.read(64 * 1024):
        h.update(chunk)
        chunks.append(chunk)
        size += len(chunk)
    raw = b"".join(chunks)
    ct = _infer_content_type(key, content_type_hint or file.content_type)
    sha = h.hexdigest()

    stmt = (
        pg_insert(Artifact)
        .values(
            id=uuid.uuid4(),
            workflow_id=workflow_id,
            step=step,
            key=key,
            attempt=attempt,
            path=None,
            content=raw,
            size_bytes=size,
            content_type=ct,
            sha256=sha,
        )
        .on_conflict_do_update(
            constraint="uq_artifact_key",
            set_={
                "path": None,
                "content": raw,
                "size_bytes": size,
                "content_type": ct,
                "sha256": sha,
            },
        )
        .returning(Artifact)
    )
    art = (await session.execute(stmt)).scalar_one()

    logger.info(
        "上传产物成功",
        workflow_id=str(workflow_id),
        step=step,
        key=key,
        attempt=attempt,
        size_bytes=size,
        sha256=sha,
        request_id=get_request_id() or "req_unknown",
    )
    return ArtifactRead.model_validate(art)


@router.put("/artifacts/{art_id}/content", response_model=ArtifactRead)
async def edit_artifact_content(
    art_id: uuid.UUID,
    body: ArtifactEditRequest,
    session: AsyncSession = Depends(get_session),
) -> ArtifactRead:
    """用户在 UI 上直接编辑产物内容；同时记一条 `artifact.edited` workflow_event。"""
    art = (
        await session.execute(select(Artifact).where(Artifact.id == art_id))
    ).scalar_one_or_none()
    if art is None:
        raise HTTPException(404, "Artifact not found")

    raw = body.content.encode("utf-8")
    new_sha256 = hashlib.sha256(raw).hexdigest()
    old_sha256 = art.sha256
    old_size = art.size_bytes

    art.content = raw
    art.size_bytes = len(raw)
    art.sha256 = new_sha256
    art.path = None  # 编辑后不再依赖 FS

    rid = get_request_id() or "req_unknown"
    session.add(
        WorkflowEvent(
            workflow_id=art.workflow_id,
            event_type="artifact.edited",
            payload={
                "artifact_id": str(art.id),
                "step": art.step,
                "key": art.key,
                "old_sha256": old_sha256,
                "new_sha256": new_sha256,
                "old_size_bytes": old_size,
                "new_size_bytes": len(raw),
                "comment": body.comment or None,
            },
            request_id=rid,
        )
    )
    await session.flush()
    logger.info(
        "用户编辑产物内容",
        artifact_id=str(art_id),
        workflow_id=str(art.workflow_id),
        step=art.step,
        key=art.key,
        size_bytes=len(raw),
        request_id=rid,
    )
    return ArtifactRead.model_validate(art)


@router.get("/workflows/{wf_id}/artifacts", response_model=list[ArtifactRead])
async def list_workflow_artifacts(
    wf_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> list[ArtifactRead]:
    result = await session.execute(
        select(Artifact).where(Artifact.workflow_id == wf_id).order_by(Artifact.step, Artifact.key)
    )
    return [ArtifactRead.model_validate(a) for a in result.scalars().all()]


@router.get("/artifacts/{art_id}/content")
async def artifact_content(
    art_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    art = (
        await session.execute(select(Artifact).where(Artifact.id == art_id))
    ).scalar_one_or_none()
    if art is None:
        raise HTTPException(404, "Artifact not found")

    ctype = art.content_type or _infer_content_type(art.key, None)

    # 优先从 DB content 读（新版上传走这条路径）
    if art.content is not None:
        return Response(content=bytes(art.content), media_type=ctype)

    # 兼容旧的共享 FS 部署：从 path 读盘
    if not art.path:
        raise HTTPException(404, "Artifact has neither content nor path")

    wf = (
        await session.execute(select(Workflow).where(Workflow.id == art.workflow_id))
    ).scalar_one()
    root = Path(wf.artifact_root).resolve()
    path = Path(art.path).resolve()
    try:
        path.relative_to(root)
    except ValueError as e:
        logger.error(
            "产物路径越界拒绝访问",
            artifact_id=str(art_id),
            path=str(path),
            root=str(root),
        )
        raise HTTPException(403, "Artifact path outside workflow root") from e
    if not path.exists():
        raise HTTPException(404, "Artifact file missing on disk")
    if ctype in _TEXT_CONTENT_TYPES or ctype.startswith("text/"):
        return Response(content=path.read_bytes(), media_type=ctype)
    return FileResponse(path=str(path), media_type=ctype, filename=art.key)


@router.get("/workflows/{wf_id}/artifacts/by-key/content")
async def artifact_content_by_key(
    wf_id: uuid.UUID,
    step: str,
    key: str,
    session: AsyncSession = Depends(get_session),
) -> Response:
    """SDK load_artifact 用：按 (workflow, step, key) 取**最新 attempt** 的内容
    （上一步重跑后下游 agent 应该用最新版作为输入）。"""
    art = (
        await session.execute(
            select(Artifact)
            .where(Artifact.workflow_id == wf_id)
            .where(Artifact.step == step)
            .where(Artifact.key == key)
            .order_by(Artifact.attempt.desc())
            .limit(1)
        )
    ).scalar_one_or_none()
    if art is None:
        raise HTTPException(404, "Artifact not found")
    ctype = art.content_type or _infer_content_type(art.key, None)
    if art.content is not None:
        return Response(content=bytes(art.content), media_type=ctype)
    if not art.path:
        raise HTTPException(404, "Artifact has neither content nor path")
    p = Path(art.path)
    if not p.exists():
        raise HTTPException(404, "Artifact file missing on disk")
    return Response(content=p.read_bytes(), media_type=ctype)
