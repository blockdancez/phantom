"""add product_candidates + candidate_id FK on product_experience_reports

Revision ID: a1c4e2f0b8d3
Revises: 38caf4419f59
Create Date: 2026-04-24 14:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "a1c4e2f0b8d3"
down_revision: Union[str, None] = "38caf4419f59"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "product_candidates",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("slug", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("homepage_url", sa.Text(), nullable=False),
        sa.Column("tagline", sa.Text(), nullable=True),
        sa.Column("discovered_from", sa.String(length=64), nullable=False),
        sa.Column("discovered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_experienced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("experience_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("slug", name="uq_product_candidates_slug"),
        sa.UniqueConstraint("homepage_url", name="uq_product_candidates_homepage_url"),
    )
    op.create_index(
        "ix_product_candidates_slug", "product_candidates", ["slug"], unique=False
    )
    op.create_index(
        "ix_product_candidates_discovered_from",
        "product_candidates",
        ["discovered_from"],
        unique=False,
    )

    # product_experience_reports.candidate_id (nullable FK).
    # Existing rows (currently 0) keep candidate_id NULL.
    # Bump product_slug capacity from 64→128 to match candidate slug length.
    with op.batch_alter_table("product_experience_reports") as batch:
        batch.alter_column(
            "product_slug",
            existing_type=sa.String(length=64),
            type_=sa.String(length=128),
            existing_nullable=False,
        )
        batch.add_column(sa.Column("candidate_id", sa.String(length=36), nullable=True))
        batch.create_foreign_key(
            "fk_product_experience_reports_candidate_id",
            "product_candidates",
            ["candidate_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_product_experience_reports_candidate_id",
        "product_experience_reports",
        ["candidate_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "ix_product_experience_reports_candidate_id",
        table_name="product_experience_reports",
    )
    with op.batch_alter_table("product_experience_reports") as batch:
        batch.drop_constraint(
            "fk_product_experience_reports_candidate_id", type_="foreignkey"
        )
        batch.drop_column("candidate_id")
        batch.alter_column(
            "product_slug",
            existing_type=sa.String(length=128),
            type_=sa.String(length=64),
            existing_nullable=False,
        )

    op.drop_index("ix_product_candidates_discovered_from", table_name="product_candidates")
    op.drop_index("ix_product_candidates_slug", table_name="product_candidates")
    op.drop_table("product_candidates")
