"""posts: published_at, is_ad, reactions, attachments; post_comments

Revision ID: f1a2b3c4d5e6
Revises: e7f8a9b0c1d2
Create Date: 2026-04-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "f1a2b3c4d5e6"
down_revision: Union[str, Sequence[str], None] = "e7f8a9b0c1d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "posts",
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "posts",
        sa.Column("is_ad", sa.Boolean(), server_default="false", nullable=False),
    )
    op.add_column("posts", sa.Column("reactions", sa.JSON(), nullable=True))
    op.add_column("posts", sa.Column("attachments", sa.JSON(), nullable=True))
    op.create_index(op.f("ix_posts_published_at"), "posts", ["published_at"], unique=False)

    op.create_table(
        "post_comments",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("post_id", sa.BigInteger(), nullable=False),
        sa.Column("source_comment_id", sa.BigInteger(), nullable=False),
        sa.Column("parent_id", sa.BigInteger(), nullable=True),
        sa.Column("from_id", sa.BigInteger(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attachments", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["parent_id"], ["post_comments.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "post_id",
            "source_comment_id",
            name="uq_post_comments_post_source_comment",
        ),
    )
    op.create_index(
        op.f("ix_post_comments_post_id"), "post_comments", ["post_id"], unique=False
    )
    op.create_index(
        op.f("ix_post_comments_parent_id"), "post_comments", ["parent_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_post_comments_parent_id"), table_name="post_comments")
    op.drop_index(op.f("ix_post_comments_post_id"), table_name="post_comments")
    op.drop_table("post_comments")
    op.drop_index(op.f("ix_posts_published_at"), table_name="posts")
    op.drop_column("posts", "attachments")
    op.drop_column("posts", "reactions")
    op.drop_column("posts", "is_ad")
    op.drop_column("posts", "published_at")
