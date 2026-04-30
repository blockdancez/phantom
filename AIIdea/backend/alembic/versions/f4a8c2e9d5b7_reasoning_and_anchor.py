"""reasoning and anchor

Revision ID: f4a8c2e9d5b7
Revises: e3f5a9c1d8b2
Create Date: 2026-04-20 12:50:00.000000

Replaces the bullet-list ``evidence`` column with two cleaner fields:

- ``source_item_id`` — UUID of the SourceItem that seeded the idea. Lets the
  detail page link the anchor to the original data record.
- ``reasoning`` — Text narrative written like a PM explaining how the idea
  came about. Replaces the previously mechanical "- r/sub: user said x"
  bullet list that read poorly.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID


revision: str = "f4a8c2e9d5b7"
down_revision: Union[str, None] = "e3f5a9c1d8b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analysis_results",
        sa.Column("source_item_id", UUID(as_uuid=True), nullable=True),
    )
    op.add_column(
        "analysis_results",
        sa.Column("reasoning", sa.Text(), nullable=True),
    )
    op.drop_column("analysis_results", "evidence")


def downgrade() -> None:
    from sqlalchemy.dialects.postgresql import JSONB

    op.add_column(
        "analysis_results",
        sa.Column("evidence", JSONB(), nullable=True),
    )
    op.drop_column("analysis_results", "reasoning")
    op.drop_column("analysis_results", "source_item_id")
