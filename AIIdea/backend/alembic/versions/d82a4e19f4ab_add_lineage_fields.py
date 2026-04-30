"""add lineage fields

Revision ID: d82a4e19f4ab
Revises: c7f31ea0b2c8
Create Date: 2026-04-20 10:45:00.000000

Adds ``source_quote`` and ``user_story`` columns to analysis_results so each
idea row can carry a concrete quote from the source item that seeded it and
a one-sentence user story. Both nullable — legacy rows stay untouched.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "d82a4e19f4ab"
down_revision: Union[str, None] = "c7f31ea0b2c8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("analysis_results", sa.Column("source_quote", sa.Text(), nullable=True))
    op.add_column("analysis_results", sa.Column("user_story", sa.Text(), nullable=True))


def downgrade() -> None:
    op.drop_column("analysis_results", "user_story")
    op.drop_column("analysis_results", "source_quote")
