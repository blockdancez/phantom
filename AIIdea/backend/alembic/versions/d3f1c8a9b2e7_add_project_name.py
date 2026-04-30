"""add project_name to analysis_results

Slug-style globally-unique short id (1-3 lowercase English words joined
by ``-``). Used as AIJuicer project_name and as a stable handle for any
downstream resource (DB / repo dir / etc.) tied to an idea.

Revision ID: d3f1c8a9b2e7
Revises: c2e8a7d6f4b9
Create Date: 2026-04-30
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "d3f1c8a9b2e7"
down_revision: Union[str, None] = "c2e8a7d6f4b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_results",
        sa.Column("project_name", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_analysis_results_project_name",
        "analysis_results",
        ["project_name"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_results_project_name", table_name="analysis_results")
    op.drop_column("analysis_results", "project_name")
