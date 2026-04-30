import uuid
from datetime import datetime

from pydantic import BaseModel, Field


class IdeaCreate(BaseModel):
    content: str = Field(..., min_length=1, max_length=5000, description="产品idea描述")


class IdeaRegenerate(BaseModel):
    rerun_instruction: str | None = Field(
        default=None,
        max_length=2000,
        description="重跑指令 / 用户反馈；可为空，等价于不带指令的重新生成",
    )


class IdeaResponse(BaseModel):
    id: uuid.UUID
    content: str
    status: str
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class IdeaListResponse(BaseModel):
    ideas: list[IdeaResponse]
    total: int


class DocumentResponse(BaseModel):
    id: uuid.UUID
    idea_id: uuid.UUID
    title: str
    content: str
    research: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class DocumentListResponse(BaseModel):
    documents: list[DocumentResponse]
    total: int


class ErrorResponse(BaseModel):
    detail: str
    request_id: str | None = None
