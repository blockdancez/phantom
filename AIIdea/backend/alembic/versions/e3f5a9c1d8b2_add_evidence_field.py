"""add evidence field

Revision ID: e3f5a9c1d8b2
Revises: d82a4e19f4ab
Create Date: 2026-04-20 11:45:00.000000

Adds ``evidence`` JSONB column to analysis_results. Each row stores a list
of corroborating signals (other supporting items from the same trend as the
anchor) so the detail page can show "xxx discussed this" / "yyy complained
about that" rather than just one anchor quote.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB


revision: str = "e3f5a9c1d8b2"
down_revision: Union[str, None] = "d82a4e19f4ab"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "analysis_results",
        sa.Column("evidence", JSONB(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("analysis_results", "evidence")
