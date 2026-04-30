"""add inspiration brief fields to product_experience_reports

Five fields (1 TEXT + 4 JSONB) backing the "产品启发 brief" view: product
thesis, structured core features (with rationale), target user profile,
differentiation opportunities, and innovation angles. All nullable —
historical 282 rows keep their old fields and render via fallback on the
detail page.

Revision ID: h7e218b95c4d
Revises: g6c104e3a2b9
Create Date: 2026-04-30
"""
from typing import Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "h7e218b95c4d"
down_revision: Union[str, None] = "g6c104e3a2b9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "product_experience_reports",
        sa.Column("product_thesis", sa.Text(), nullable=True),
    )
    op.add_column(
        "product_experience_reports",
        sa.Column("core_features", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "product_experience_reports",
        sa.Column("target_user_profile", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )
    op.add_column(
        "product_experience_reports",
        sa.Column(
            "differentiation_opportunities",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
    )
    op.add_column(
        "product_experience_reports",
        sa.Column(
            "innovation_angles", postgresql.JSONB(astext_type=sa.Text()), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("product_experience_reports", "innovation_angles")
    op.drop_column("product_experience_reports", "differentiation_opportunities")
    op.drop_column("product_experience_reports", "target_user_profile")
    op.drop_column("product_experience_reports", "core_features")
    op.drop_column("product_experience_reports", "product_thesis")
