# backend/src/models/product_experience_report.py
import uuid
from datetime import datetime

from sqlalchemy import Column, DateTime, Float, ForeignKey, String, Text
from sqlalchemy.dialects.postgresql import JSONB, UUID

from src.models.source_item import Base  # 复用现有 declarative Base


class ProductExperienceReport(Base):
    """一次产品体验的结构化报告（一个 product × 一次 run = 一行）。"""

    __tablename__ = "product_experience_reports"

    id = Column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)

    # FK to product_candidates — nullable so historical rows survive
    # candidate deletion (ON DELETE SET NULL) and so partial inserts
    # don't blow up if discovery hasn't run yet.
    candidate_id = Column(
        String(36),
        ForeignKey("product_candidates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )

    # 体验对象快照（冗余，保留以便 candidate 被删后报告仍可读）
    product_slug = Column(String(128), nullable=False, index=True)
    product_url = Column(Text, nullable=False)
    product_name = Column(String(256), nullable=False)

    # 运行元数据
    run_started_at = Column(DateTime(timezone=True), nullable=False)
    run_completed_at = Column(DateTime(timezone=True), nullable=True)
    status = Column(String(16), nullable=False)  # completed | partial | failed
    failure_reason = Column(Text, nullable=True)

    # 登录情况
    login_used = Column(String(16), nullable=False)  # google | none | failed | skipped

    # Slug-style globally-unique short id (mirrors AnalysisResult.project_name).
    # Format: 1-3 lowercase English words joined by "-"; collision suffix
    # "-<4 lowercase alphanum>" appended at insert time.
    project_name = Column(String(64), nullable=True, unique=True, index=True)

    # Set after a successful AIJuicer ``create_workflow`` call. Used as a
    # badge in the UI ("已入流") and for cross-system traceability.
    aijuicer_workflow_id = Column(String(64), nullable=True, index=True)

    # 借鉴启发字段（"产品启发 brief"，给"参照思路 + 创新差异化"用）
    # 旧字段（summary_zh/feature_inventory/strengths/weaknesses 等）仍保留做向后兼容。
    # ----
    # product_thesis: 产品核心理念 / 差异化卖点（一句话讲清"用户为什么选它"）
    product_thesis = Column(Text, nullable=True)
    # core_features: list[{name, priority: must|should|nice, where_seen, rationale}]
    core_features = Column(JSONB, nullable=True)
    # target_user_profile: {persona, scenarios:[str], pain_points:[str], why_this_product:str}
    target_user_profile = Column(JSONB, nullable=True)
    # differentiation_opportunities: list[{observation, opportunity, why_it_matters}]
    differentiation_opportunities = Column(JSONB, nullable=True)
    # innovation_angles: list[{angle, hypothesis, examples:[str]}]
    innovation_angles = Column(JSONB, nullable=True)

    # 报告主体
    overall_ux_score = Column(Float, nullable=True)  # 0-10（与 analysis_results.overall_score 对齐）
    summary_zh = Column(Text, nullable=True)
    feature_inventory = Column(JSONB, nullable=True)  # list[{name, where_found, notes}]
    strengths = Column(Text, nullable=True)
    weaknesses = Column(Text, nullable=True)
    monetization_model = Column(Text, nullable=True)
    target_user = Column(Text, nullable=True)

    # 媒体 + trace
    screenshots = Column(JSONB, nullable=True)  # list[{name, path, taken_at}]
    agent_trace = Column(JSONB, nullable=True)

    created_at = Column(DateTime(timezone=True), nullable=False, default=datetime.utcnow)
