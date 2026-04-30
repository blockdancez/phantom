"""artifact per-attempt rows

唯一约束从 (workflow_id, step, key) 改为 (workflow_id, step, key, attempt)，
以保留每次 agent 重跑的输出。

Revision ID: 0004_artifact_attempt
Revises: 0003_artifact_content_in_db
Create Date: 2026-04-29
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0004_artifact_attempt"
down_revision = "0003_artifact_content_in_db"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 加 attempt 列；老数据全部回填 1（无版本信息可用，且语义上"已存在 = 至少跑过一次"）
    op.add_column(
        "artifacts",
        sa.Column("attempt", sa.Integer(), nullable=False, server_default="1"),
    )
    # 把 server_default 移除，让以后插入必须显式提供
    op.alter_column("artifacts", "attempt", server_default=None)

    # 删旧约束、加新约束（key + attempt 联合唯一）
    op.drop_constraint("uq_artifact_key", "artifacts", type_="unique")
    op.create_unique_constraint(
        "uq_artifact_key",
        "artifacts",
        ["workflow_id", "step", "key", "attempt"],
    )


def downgrade() -> None:
    op.drop_constraint("uq_artifact_key", "artifacts", type_="unique")
    op.create_unique_constraint(
        "uq_artifact_key",
        "artifacts",
        ["workflow_id", "step", "key"],
    )
    op.drop_column("artifacts", "attempt")
