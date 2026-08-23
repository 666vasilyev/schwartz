"""lemma buffer: lemma_buffer_entries table

Revision ID: v0w1x2y3z4a5
Revises: u9v0w1x2y3z4
Create Date: 2026-08-23
"""
from alembic import op
import sqlalchemy as sa

revision = "v0w1x2y3z4a5"
down_revision = "u9v0w1x2y3z4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "lemma_buffer_entries",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("lemma", sa.String(255), nullable=False),
        sa.Column("raw_text", sa.String(255), nullable=False),
        sa.Column("times_selected", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("source_post_id", sa.BigInteger(), nullable=True),
        sa.Column("source_cluster_id", sa.BigInteger(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_post_id"], ["posts.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_cluster_id"], ["story_clusters.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "lemma", name="uq_lemma_buffer_user_lemma"),
    )
    op.create_index("ix_lemma_buffer_entries_user_id", "lemma_buffer_entries", ["user_id"])


def downgrade() -> None:
    op.drop_table("lemma_buffer_entries")
