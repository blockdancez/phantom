import uuid
from datetime import datetime
from pydantic import BaseModel


class SourceItemBase(BaseModel):
    source: str
    title: str
    url: str
    content: str
    raw_data: dict = {}


class SourceItemRead(SourceItemBase):
    id: uuid.UUID
    category: str | None = None
    tags: list[str] | None = None
    score: float | None = None
    summary_zh: str | None = None
    problem: str | None = None
    opportunity: str | None = None
    target_user: str | None = None
    why_now: str | None = None
    collected_at: datetime
    processed: bool
    created_at: datetime

    # Populated by the API layer so /sources/[id] can link to the analysis
    # report that was derived from this item (feature-9 关联交互流).
    analysis_result_id: uuid.UUID | None = None

    model_config = {"from_attributes": True}


class SourceItemList(BaseModel):
    items: list[SourceItemRead]
    total: int
    page: int
    # Plan contract (feature-5) says ``per_page``. Keep the internal
    # attribute named the same so responses carry the contracted field name.
    per_page: int
