"""sources.extra JSON; posts.source_id, posts.external_id

Revision ID: c9a8b7c6d5e4
Revises: b3e4f5a6c7d8
Create Date: 2026-04-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "c9a8b7c6d5e4"
down_revision: Union[str, Sequence[str], None] = "b3e4f5a6c7d8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("extra", sa.JSON(), nullable=True))
    op.add_column("posts", sa.Column("source_id", sa.Integer(), nullable=True))
    op.add_column(
        "posts", sa.Column("external_id", sa.String(length=512), nullable=True)
    )
    op.create_index(op.f("ix_posts_source_id"), "posts", ["source_id"], unique=False)
    op.create_index(
        op.f("ix_posts_external_id"), "posts", ["external_id"], unique=False
    )
    op.create_foreign_key(
        "fk_posts_source_id_sources",
        "posts",
        "sources",
        ["source_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index(
        "uq_posts_source_external",
        "posts",
        ["source_id", "external_id"],
        unique=True,
        postgresql_where=sa.text(
            "source_id IS NOT NULL AND external_id IS NOT NULL"
        ),
    )


def downgrade() -> None:
    op.drop_index("uq_posts_source_external", table_name="posts")
    op.drop_constraint("fk_posts_source_id_sources", "posts", type_="foreignkey")
    op.drop_index(op.f("ix_posts_external_id"), table_name="posts")
    op.drop_index(op.f("ix_posts_source_id"), table_name="posts")
    op.drop_column("posts", "external_id")
    op.drop_column("posts", "source_id")
    op.drop_column("sources", "extra")
