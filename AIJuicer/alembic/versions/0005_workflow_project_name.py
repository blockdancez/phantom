"""add workflows.project_name (slug, unique)

Revision ID: 0005_workflow_project_name
Revises: 0004_artifact_attempt
Create Date: 2026-04-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0005_workflow_project_name"
down_revision = "0004_artifact_attempt"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # nullable=True：旧工作流没法回填，只能后续给个空值；新工作流强制写入
    op.add_column("workflows", sa.Column("project_name", sa.Text(), nullable=True))
    op.create_unique_constraint("uq_workflows_project_name", "workflows", ["project_name"])


def downgrade() -> None:
    op.drop_constraint("uq_workflows_project_name", "workflows", type_="unique")
    op.drop_column("workflows", "project_name")
