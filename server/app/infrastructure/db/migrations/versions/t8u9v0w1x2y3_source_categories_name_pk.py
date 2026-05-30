"""source_categories: make name the PK, drop id; retype junction table

Revision ID: t8u9v0w1x2y3
Revises: s7t8u9v0w1x2
Create Date: 2026-05-31
"""
from alembic import op
import sqlalchemy as sa

revision = "t8u9v0w1x2y3"
down_revision = "s7t8u9v0w1x2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # 1. Drop junction table (references source_categories.id)
    op.drop_table("source_category_links")

    # 2. Drop PK on source_categories (id), make name the PK
    op.drop_constraint("source_categories_pkey", "source_categories", type_="primary")
    op.drop_column("source_categories", "id")
    # name already has a UNIQUE constraint — promote it to PK
    op.execute("ALTER TABLE source_categories ADD PRIMARY KEY (name);")
    # drop the now-redundant unique index on name if it exists
    op.execute(
        "DROP INDEX IF EXISTS source_categories_name_key;"
    )

    # 3. Recreate junction table keyed by category_name
    op.create_table(
        "source_category_links",
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("category_name", sa.String(255), nullable=False),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["category_name"], ["source_categories.name"],
            ondelete="CASCADE", onupdate="CASCADE",
        ),
        sa.PrimaryKeyConstraint("source_id", "category_name"),
    )


def downgrade() -> None:
    op.drop_table("source_category_links")

    op.add_column(
        "source_categories",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
    )
    op.execute(
        "CREATE SEQUENCE IF NOT EXISTS source_categories_id_seq;"
        "ALTER TABLE source_categories ALTER COLUMN id SET DEFAULT nextval('source_categories_id_seq');"
        "UPDATE source_categories SET id = nextval('source_categories_id_seq');"
    )
    op.drop_constraint("source_categories_pkey", "source_categories", type_="primary")
    op.create_primary_key("source_categories_pkey", "source_categories", ["id"])
    op.create_unique_constraint("source_categories_name_key", "source_categories", ["name"])

    op.create_table(
        "source_category_links",
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("category_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["category_id"], ["source_categories.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id", "category_id"),
    )
