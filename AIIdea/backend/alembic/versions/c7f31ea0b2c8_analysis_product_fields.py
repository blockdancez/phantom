"""analysis product fields

Revision ID: c7f31ea0b2c8
Revises: b9ba9e1280e4
Create Date: 2026-04-20 09:30:00.000000

Adds the 5 product-focused fields to analysis_results and relaxes the legacy
columns to nullable so new runs can skip them. The legacy columns stay in
place until a follow-up cleanup migration — they are still useful as raw
fallbacks during backfill.
"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c7f31ea0b2c8"
down_revision: Union[str, None] = "b9ba9e1280e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("analysis_results", sa.Column("product_idea", sa.Text(), nullable=True))
    op.add_column("analysis_results", sa.Column("target_audience", sa.Text(), nullable=True))
    op.add_column("analysis_results", sa.Column("use_case", sa.Text(), nullable=True))
    op.add_column("analysis_results", sa.Column("pain_points", sa.Text(), nullable=True))
    op.add_column("analysis_results", sa.Column("key_features", sa.Text(), nullable=True))

    # Legacy columns — relax to nullable so new rows don't need them.
    op.alter_column("analysis_results", "idea_description", nullable=True)
    op.alter_column("analysis_results", "market_analysis", nullable=True)
    op.alter_column("analysis_results", "tech_feasibility", nullable=True)


def downgrade() -> None:
    op.alter_column("analysis_results", "tech_feasibility", nullable=False)
    op.alter_column("analysis_results", "market_analysis", nullable=False)
    op.alter_column("analysis_results", "idea_description", nullable=False)

    op.drop_column("analysis_results", "key_features")
    op.drop_column("analysis_results", "pain_points")
    op.drop_column("analysis_results", "use_case")
    op.drop_column("analysis_results", "target_audience")
    op.drop_column("analysis_results", "product_idea")
