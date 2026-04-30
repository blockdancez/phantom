"""API 请求 / 响应 Pydantic 模型。"""

from __future__ import annotations

import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class InitialArtifact(BaseModel):
    """create_workflow 时随请求附带的预制产物。

    用法：producer 已经有 idea step 的完整产出时，直接传进来——scheduler 入库并跳过
    idea step 的 RUNNING 阶段，避免"自己提交自己消费"的回环。一次可以传多个 step 的
    多份产物；artifact 都按 attempt=1 写入。"""

    step: str = Field(min_length=1)
    key: str = Field(min_length=1)
    content: str  # utf-8 文本。二进制场景请走单独 upload 端点
    content_type: str | None = None


class WorkflowCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    # 调用方负责给一个项目 slug（小写英文 + 短横线）。
    # 撞名时 scheduler 会自动追加 4 位随机字母后缀，所以 caller 不必预先查重。
    project_name: str = Field(min_length=1, max_length=80)
    input: dict
    approval_policy: dict = Field(default_factory=dict)
    initial_artifacts: list[InitialArtifact] = Field(default_factory=list)


class WorkflowRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    project_name: str | None = None
    status: str
    input: dict
    approval_policy: dict
    current_step: str | None
    failed_step: str | None
    artifact_root: str
    created_at: datetime
    updated_at: datetime


class WorkflowListResponse(BaseModel):
    items: list[WorkflowRead]
    total: int
    page: int
    page_size: int


class TaskStartRequest(BaseModel):
    agent_id: str


class TaskCompleteRequest(BaseModel):
    output: dict = Field(default_factory=dict)


class TaskFailRequest(BaseModel):
    error: str
    retryable: bool = True


class TaskHeartbeatRequest(BaseModel):
    message: str | None = None


class ApprovalRequest(BaseModel):
    decision: str
    step: str | None = None
    comment: str | None = None
    modified_input: dict | None = None


class AgentRegisterRequest(BaseModel):
    name: str
    step: str
    metadata: dict | None = None


class AgentRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    step: str
    status: str
    last_seen_at: datetime
    host: str | None = None
    port: int | None = None
    pid: int | None = None
    hostname: str | None = None


class AgentRegisterResponse(AgentRead):
    """register 专用响应：除 AgentRead 外附带 SDK 需要的 redis_url。

    这样 SDK 不必单独配 redis；注册时就一次拿到。
    """

    redis_url: str


class ArtifactCreate(BaseModel):
    workflow_id: uuid.UUID
    step: str
    key: str
    path: str
    size_bytes: int
    content_type: str | None = None
    sha256: str | None = None


class ArtifactEditRequest(BaseModel):
    content: str
    comment: str | None = None


class ArtifactRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    workflow_id: uuid.UUID
    step: str
    key: str
    attempt: int
    # path 仅给共享 FS 旧记录用；DB 内嵌内容的新记录此字段为 None
    path: str | None = None
    size_bytes: int
    content_type: str | None
    sha256: str | None
    created_at: datetime
