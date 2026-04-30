"""add product_type to analysis_results

Mirrors AgentReport.digital_product_form enum so the UI can show a
localized badge ("网站 / 移动 App / 浏览器插件 / CLI / 桌面应用 / ...").

Revision ID: e7b2c4d8a531
Revises: d3f1c8a9b2e7
Create Date: 2026-04-30
"""
from typing import Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7b2c4d8a531"
down_revision: Union[str, None] = "d3f1c8a9b2e7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "analysis_results",
        sa.Column("product_type", sa.String(length=32), nullable=True),
    )
    op.create_index(
        "ix_analysis_results_product_type",
        "analysis_results",
        ["product_type"],
    )


def downgrade() -> None:
    op.drop_index("ix_analysis_results_product_type", table_name="analysis_results")
    op.drop_column("analysis_results", "product_type")
