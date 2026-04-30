"""artifact content stored in DB (drop FS dependency)

Revision ID: 0003_artifact_content_in_db
Revises: 0002_finder_to_idea
Create Date: 2026-04-28
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003_artifact_content_in_db"
down_revision = "0002_finder_to_idea"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 把 artifact 字节本身搬进 DB；以前的 path 列保留做向前兼容（旧记录读盘），
    # 新写入只用 content。
    op.add_column("artifacts", sa.Column("content", sa.LargeBinary(), nullable=True))
    op.alter_column("artifacts", "path", existing_type=sa.Text(), nullable=True)


def downgrade() -> None:
    op.alter_column("artifacts", "path", existing_type=sa.Text(), nullable=False)
    op.drop_column("artifacts", "content")
