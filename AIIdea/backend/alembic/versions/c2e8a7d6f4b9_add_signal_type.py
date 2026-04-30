"""add signal_type to source_items

Coarse classifier ("pain_point" / "question" / "launch" / "story" / "news"
/ "other") set by the analyzer; downstream agent uses it to skip launch
posts and storytelling threads when picking idea anchors.

Revision ID: c2e8a7d6f4b9
Revises: a1c4e2f0b8d3
Create Date: 2026-04-27
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "c2e8a7d6f4b9"
down_revision: Union[str, None] = "a1c4e2f0b8d3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "source_items",
        sa.Column("signal_type", sa.String(length=20), nullable=True),
    )
    op.create_index(
        "ix_source_items_signal_type",
        "source_items",
        ["signal_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_source_items_signal_type", table_name="source_items")
    op.drop_column("source_items", "signal_type")
