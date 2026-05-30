"""source_categories: drop slug column

Revision ID: n2o3p4q5r6s7
Revises: m1n2o3p4q5r6
Create Date: 2026-05-30
"""
from alembic import op

revision = "n2o3p4q5r6s7"
down_revision = "m1n2o3p4q5r6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("ix_source_categories_slug", table_name="source_categories")
    op.drop_column("source_categories", "slug")


def downgrade() -> None:
    import sqlalchemy as sa
    op.add_column(
        "source_categories",
        sa.Column("slug", sa.String(64), nullable=True),
    )
    op.create_index("ix_source_categories_slug", "source_categories", ["slug"], unique=True)
