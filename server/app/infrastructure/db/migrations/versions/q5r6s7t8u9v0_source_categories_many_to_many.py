"""sources: replace category_id FK with many-to-many source_category_links

Revision ID: q5r6s7t8u9v0
Revises: p4q5r6s7t8u9
Create Date: 2026-05-30
"""
from alembic import op
import sqlalchemy as sa

revision = "q5r6s7t8u9v0"
down_revision = "p4q5r6s7t8u9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create junction table
    op.create_table(
        "source_category_links",
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["source_categories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id", "category_id"),
    )

    # Migrate existing category_id → junction rows
    op.execute("""
        INSERT INTO source_category_links (source_id, category_id)
        SELECT id, category_id FROM sources
        WHERE category_id IS NOT NULL
        ON CONFLICT DO NOTHING
    """)

    # Drop old FK column
    op.drop_index("ix_sources_category_id", table_name="sources", if_exists=True)
    op.drop_column("sources", "category_id")


def downgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("category_id", sa.Integer(), nullable=True),
    )
    op.create_foreign_key(
        "sources_category_id_fkey",
        "sources", "source_categories",
        ["category_id"], ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_sources_category_id", "sources", ["category_id"])

    # Restore one category per source (pick any)
    op.execute("""
        UPDATE sources s
        SET category_id = (
            SELECT category_id FROM source_category_links
            WHERE source_id = s.id
            LIMIT 1
        )
    """)

    op.drop_table("source_category_links")
