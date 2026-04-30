"""finder 重命名为 idea：原地迁移所有历史数据。

Revision ID: 0002_finder_to_idea
Revises: 0001_initial_schema
Create Date: 2026-04-23

背景：流水线首步从 "finder" 重命名为 "idea"（对应 AIFinder 外部源头 agent 之
下的首个 pipeline step）。state、step 字符串在 6 张表里都要更新。
"""

from __future__ import annotations

from alembic import op

revision = "0002_finder_to_idea"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE workflows SET status='IDEA_RUNNING' WHERE status='FINDER_RUNNING'"
    )
    op.execute(
        "UPDATE workflows SET status='IDEA_DONE' WHERE status='FINDER_DONE'"
    )
    op.execute(
        "UPDATE workflows SET current_step='idea' WHERE current_step='finder'"
    )
    op.execute(
        "UPDATE workflows SET failed_step='idea' WHERE failed_step='finder'"
    )
    op.execute("UPDATE step_executions SET step='idea' WHERE step='finder'")
    op.execute("UPDATE artifacts SET step='idea' WHERE step='finder'")
    op.execute("UPDATE approvals SET step='idea' WHERE step='finder'")
    op.execute("UPDATE agents SET step='idea' WHERE step='finder'")
    # workflow_events.payload 里 payload->>'step'='finder' 的条目也顺手改，
    # 避免 UI 上事件时间线看到混合名。
    op.execute(
        "UPDATE workflow_events "
        "SET payload = jsonb_set(payload, '{step}', '\"idea\"') "
        "WHERE payload->>'step' = 'finder'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE workflows SET status='FINDER_RUNNING' WHERE status='IDEA_RUNNING'"
    )
    op.execute(
        "UPDATE workflows SET status='FINDER_DONE' WHERE status='IDEA_DONE'"
    )
    op.execute(
        "UPDATE workflows SET current_step='finder' WHERE current_step='idea'"
    )
    op.execute(
        "UPDATE workflows SET failed_step='finder' WHERE failed_step='idea'"
    )
    op.execute("UPDATE step_executions SET step='finder' WHERE step='idea'")
    op.execute("UPDATE artifacts SET step='finder' WHERE step='idea'")
    op.execute("UPDATE approvals SET step='finder' WHERE step='idea'")
    op.execute("UPDATE agents SET step='finder' WHERE step='idea'")
    op.execute(
        "UPDATE workflow_events "
        "SET payload = jsonb_set(payload, '{step}', '\"finder\"') "
        "WHERE payload->>'step' = 'idea'"
    )
