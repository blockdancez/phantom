import uuid
from datetime import datetime

from sqlalchemy import String, Text, Float, Boolean, DateTime, func
from sqlalchemy.dialects.postgresql import UUID, JSONB, ARRAY
from sqlalchemy.orm import Mapped, mapped_column

from src.db import Base


class SourceItem(Base):
    __tablename__ = "source_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    source: Mapped[str] = mapped_column(String(50), nullable=False, index=True)
    title: Mapped[str] = mapped_column(String(500), nullable=False)
    url: Mapped[str] = mapped_column(String(2000), nullable=False, unique=True)
    content: Mapped[str] = mapped_column(Text, nullable=False, default="")
    raw_data: Mapped[dict] = mapped_column(JSONB, nullable=False, default=dict)
    category: Mapped[str | None] = mapped_column(String(100), nullable=True)
    tags: Mapped[list[str] | None] = mapped_column(ARRAY(String), nullable=True)
    score: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Structured insights produced by the Analyzer (see processors/analyzer.py)
    summary_zh: Mapped[str | None] = mapped_column(Text, nullable=True)
    problem: Mapped[str | None] = mapped_column(Text, nullable=True)
    opportunity: Mapped[str | None] = mapped_column(Text, nullable=True)
    target_user: Mapped[str | None] = mapped_column(Text, nullable=True)
    why_now: Mapped[str | None] = mapped_column(Text, nullable=True)

    # Coarse type tag the analyzer assigns so downstream agent only anchors
    # ideas off "pain_point" / "question" items. "launch" / "story" / "news"
    # rows are still ingested + processed (we want them in the table for
    # search) but get filtered out of search_items by default.
    signal_type: Mapped[str | None] = mapped_column(String(20), nullable=True, index=True)

    collected_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
    processed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False, server_default=func.now())
