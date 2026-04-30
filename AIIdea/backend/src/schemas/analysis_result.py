import uuid
from datetime import datetime
from pydantic import BaseModel


class AnalysisResultRead(BaseModel):
    id: uuid.UUID
    idea_title: str
    overall_score: float
    project_name: str | None = None
    product_type: str | None = None
    aijuicer_workflow_id: str | None = None

    product_idea: str | None = None
    target_audience: str | None = None
    use_case: str | None = None
    pain_points: str | None = None
    key_features: str | None = None

    source_quote: str | None = None
    user_story: str | None = None
    source_item_id: uuid.UUID | None = None
    reasoning: str | None = None
    # Joined in by the API layer for convenience — the title + URL of the
    # SourceItem identified by source_item_id.
    source_item_title: str | None = None
    source_item_url: str | None = None

    source_item_ids: list[uuid.UUID]
    # Legacy rows predate the structured trace; per feature-6 edge case the
    # detail endpoint must return ``agent_trace: null`` instead of 500.
    agent_trace: dict | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class AnalysisResultList(BaseModel):
    items: list[AnalysisResultRead]
    total: int
    page: int
    per_page: int
