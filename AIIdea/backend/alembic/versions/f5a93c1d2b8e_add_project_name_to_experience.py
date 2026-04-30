"""add project_name to product_experience_reports

Mirrors AnalysisResult.project_name — slug-style globally-unique short id
used as AIJuicer project_name + handle for downstream tooling.

Revision ID: f5a93c1d2b8e
Revises: e7b2c4d8a531
Create Date: 2026-04-30
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "f5a93c1d2b8e"
down_revision: Union[str, None] = "e7b2c4d8a531"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_experience_reports",
        sa.Column("project_name", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_product_experience_reports_project_name",
        "product_experience_reports",
        ["project_name"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_experience_reports_project_name",
        table_name="product_experience_reports",
    )
    op.drop_column("product_experience_reports", "project_name")
