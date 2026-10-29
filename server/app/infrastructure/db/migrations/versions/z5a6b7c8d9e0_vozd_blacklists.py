"""vozd: чёрные списки пользователей и слов социальных групп

Revision ID: z5a6b7c8d9e0
Revises: y4z5a6b7c8d9
Create Date: 2026-10-29
"""
from alembic import op
import sqlalchemy as sa

revision = "z5a6b7c8d9e0"
down_revision = "y4z5a6b7c8d9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vozd_blacklist_users",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("social_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("external_id", sa.BigInteger(), nullable=False),
        sa.Column("note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("group_id", "platform", "external_id", name="uq_vozd_blacklist_users"),
    )
    op.create_index("ix_vozd_blacklist_users_group_id", "vozd_blacklist_users", ["group_id"])
    op.create_table(
        "vozd_blacklist_words",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("social_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("word", sa.String(255), nullable=False),
        sa.Column("lemma", sa.String(255), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("group_id", "lemma", name="uq_vozd_blacklist_words"),
    )
    op.create_index("ix_vozd_blacklist_words_group_id", "vozd_blacklist_words", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_vozd_blacklist_words_group_id", table_name="vozd_blacklist_words")
    op.drop_table("vozd_blacklist_words")
    op.drop_index("ix_vozd_blacklist_users_group_id", table_name="vozd_blacklist_users")
    op.drop_table("vozd_blacklist_users")
