import uuid
from datetime import datetime

from sqlalchemy import String, Text, Float, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base


class AnalysisResult(Base):
    __tablename__ = "analysis_results"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    idea_title: Mapped[str] = mapped_column(String(500), nullable=False)
    overall_score: Mapped[float] = mapped_column(Float, nullable=False)

    # Slug-style globally-unique short id for downstream use (DB names,
    # repo dirs, AIJuicer project_name). Format: 1-3 lowercase English
    # words joined by ``-``; on uniqueness conflict a ``-<4 lowercase
    # alphanum>`` suffix is appended at insert time (see jobs.py and
    # pipeline.py write paths).
    project_name: Mapped[str | None] = mapped_column(
        String(64), nullable=True, unique=True, index=True
    )

    # Product type tag: web / mobile_app / chrome_extension / api / sdk /
    # ai_app / bot / cli / desktop / saas. Mirrors the LLM-side
    # ``digital_product_form`` enum so the UI can show a localized badge.
    product_type: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)

    # Set after a successful AIJuicer ``create_workflow`` call. Doubles as
    # "this idea has entered the AIJuicer pipeline" flag the UI uses to
    # render a badge.
    aijuicer_workflow_id: Mapped[str | None] = mapped_column(
        String(64), nullable=True, index=True
    )

    # Product-focused fields surfaced in the UI.
    product_idea: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_audience: Mapped[str | None] = mapped_column(Text, nullable=True)
    use_case: Mapped[str | None] = mapped_column(Text, nullable=True)
    pain_points: Mapped[str | None] = mapped_column(Text, nullable=True)
    key_features: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Lineage: the actual Reddit/RSS quote + one-sentence user story. Both are
    # only populated on new runs; legacy rows remain NULL.
    source_quote: Mapped[str | None] = mapped_column(Text, nullable=True)
    user_story: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Anchor: the SourceItem this idea grew out of. Lets the UI show the
    # original data record's title as a link to /sources/{id}.
    source_item_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), nullable=True
    )
    # Narrative "why this idea came about", written like a PM. Replaces the
    # old bullet-list evidence that read mechanically.
    reasoning: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Legacy columns — kept on disk as raw-text fallback during migrations.
    idea_description: Mapped[str | None] = mapped_column(Text, nullable=True)
    market_analysis: Mapped[str | None] = mapped_column(Text, nullable=True)
    tech_feasibility: Mapped[str | None] = mapped_column(Text, nullable=True)

    source_item_ids: Mapped[list[str]] = mapped_column(ARRAY(UUID(as_uuid=True)), nullable=False, default=list)
    agent_trace: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
