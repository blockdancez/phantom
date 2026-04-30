# backend/src/schemas/product_experience_report.py
from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


class FeatureInventoryItem(BaseModel):
    """LLM 输出的一项功能盘点条目。"""

    name: str
    where_found: str = ""
    notes: str = ""


class ScreenshotEntry(BaseModel):
    name: str
    path: str  # 相对 backend/data/product_screenshots/ 的路径，前端拼 /static/screenshots/<path>
    taken_at: datetime


# ---- 借鉴启发 brief 子模型 ----

class CoreFeature(BaseModel):
    """核心功能 + 设计意图。priority 限定为 must / should / nice。"""

    name: str
    priority: str | None = None  # must | should | nice
    where_seen: str | None = None
    rationale: str | None = None  # 这个功能背后的产品思路（学什么、为什么这样做）


class TargetUserProfile(BaseModel):
    persona: str | None = None
    scenarios: list[str] = Field(default_factory=list)
    pain_points: list[str] = Field(default_factory=list)
    why_this_product: str | None = None


class DifferentiationOpportunity(BaseModel):
    """这个产品的局限/盲点，以及我能怎么补位。"""

    observation: str
    opportunity: str | None = None
    why_it_matters: str | None = None


class InnovationAngle(BaseModel):
    """创新切入点：在哪个维度可以做更好。"""

    angle: str  # 用户场景拓展 / AI 增强 / 协作模式 / 商业模式 / 工作流简化 等
    hypothesis: str | None = None
    examples: list[str] = Field(default_factory=list)


class ProductExperienceReportOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_slug: str
    product_url: str
    product_name: str
    project_name: str | None = None
    aijuicer_workflow_id: str | None = None
    run_started_at: datetime
    run_completed_at: datetime | None
    status: str
    failure_reason: str | None
    login_used: str
    overall_ux_score: float | None
    # 借鉴启发字段
    product_thesis: str | None = None
    core_features: list[CoreFeature] | None = None
    target_user_profile: TargetUserProfile | None = None
    differentiation_opportunities: list[DifferentiationOpportunity] | None = None
    innovation_angles: list[InnovationAngle] | None = None
    # 兼容旧字段
    summary_zh: str | None
    feature_inventory: list[FeatureInventoryItem] | None
    strengths: str | None
    weaknesses: str | None
    monetization_model: str | None
    target_user: str | None
    screenshots: list[ScreenshotEntry] | None
    agent_trace: dict[str, Any] | None
    created_at: datetime


class ProductExperienceReportListOut(BaseModel):
    """列表用裁剪版本，不带 trace / 截图详情，只带摘要字段。"""

    model_config = ConfigDict(from_attributes=True)

    id: UUID
    product_slug: str
    product_name: str
    product_url: str
    project_name: str | None = None
    aijuicer_workflow_id: str | None = None
    run_completed_at: datetime | None
    status: str
    login_used: str
    overall_ux_score: float | None
    product_thesis: str | None = None  # 列表卡副标题用
    summary_zh: str | None
    screenshots_count: int = Field(default=0)


class ProductExperienceListResponse(BaseModel):
    items: list[ProductExperienceReportListOut]
    total: int
    page: int
    per_page: int
