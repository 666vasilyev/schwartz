"""source_categories table + category_id FK on sources

Revision ID: m1n2o3p4q5r6
Revises: l1m2n3o4p5q6
Create Date: 2026-05-30
"""
from alembic import op
import sqlalchemy as sa

revision = "m1n2o3p4q5r6"
down_revision = "l1m2n3o4p5q6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "source_categories",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False, unique=True),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.add_column(
        "sources",
        sa.Column("category_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "fk_sources_category_id",
        "sources",
        "source_categories",
        ["category_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_sources_category_id", "sources", ["category_id"])


def downgrade() -> None:
    op.drop_index("ix_sources_category_id", table_name="sources")
    op.drop_constraint("fk_sources_category_id", "sources", type_="foreignkey")
    op.drop_column("sources", "category_id")
    op.drop_table("source_categories")
