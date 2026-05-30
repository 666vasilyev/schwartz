"""sources: set category_id=1 for all rows, drop legacy category column

Revision ID: o3p4q5r6s7t8
Revises: n2o3p4q5r6s7
Create Date: 2026-05-30
"""
from alembic import op
import sqlalchemy as sa

revision = "o3p4q5r6s7t8"
down_revision = "n2o3p4q5r6s7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Проставить category_id = 1 всем источникам у которых он не задан
    op.execute("UPDATE sources SET category_id = 1 WHERE category_id IS NULL")

    # Удалить старое строковое поле
    op.drop_index("ix_sources_category", table_name="sources", if_exists=True)
    op.drop_column("sources", "category")


def downgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("category", sa.String(32), nullable=True),
    )
    op.create_index("ix_sources_category", "sources", ["category"])
