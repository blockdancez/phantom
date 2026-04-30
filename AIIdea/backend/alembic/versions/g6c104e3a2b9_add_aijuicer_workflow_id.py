"""add aijuicer_workflow_id to analysis_results + product_experience_reports

Set on successful ``create_workflow`` from the AIJuicer publisher; used as
a "已入流" badge in the UI and as a cross-system handle.

Revision ID: g6c104e3a2b9
Revises: f5a93c1d2b8e
Create Date: 2026-04-30
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "g6c104e3a2b9"
down_revision: Union[str, None] = "f5a93c1d2b8e"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_results",
        sa.Column("aijuicer_workflow_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_analysis_results_aijuicer_workflow_id",
        "analysis_results",
        ["aijuicer_workflow_id"],
    )
    op.add_column(
        "product_experience_reports",
        sa.Column("aijuicer_workflow_id", sa.String(length=64), nullable=True),
    )
    op.create_index(
        "ix_product_experience_reports_aijuicer_workflow_id",
        "product_experience_reports",
        ["aijuicer_workflow_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_experience_reports_aijuicer_workflow_id",
        table_name="product_experience_reports",
    )
    op.drop_column("product_experience_reports", "aijuicer_workflow_id")
    op.drop_index(
        "ix_analysis_results_aijuicer_workflow_id",
        table_name="analysis_results",
    )
    op.drop_column("analysis_results", "aijuicer_workflow_id")
