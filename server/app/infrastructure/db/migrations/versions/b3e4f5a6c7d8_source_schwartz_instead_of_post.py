"""post_schwartz -> source_schwartz

Revision ID: b3e4f5a6c7d8
Revises: f920d3652acd
Create Date: 2026-04-24

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "b3e4f5a6c7d8"
down_revision: Union[str, Sequence[str], None] = "f920d3652acd"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.drop_index(
        op.f("ix_post_schwartz_analysis_post_id"), table_name="post_schwartz_analysis"
    )
    op.drop_table("post_schwartz_analysis")

    op.create_table(
        "source_schwartz_analysis",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("self_direction", sa.Float(), nullable=False),
        sa.Column("stimulation", sa.Float(), nullable=False),
        sa.Column("hedonism", sa.Float(), nullable=False),
        sa.Column("achievement", sa.Float(), nullable=False),
        sa.Column("power", sa.Float(), nullable=False),
        sa.Column("security", sa.Float(), nullable=False),
        sa.Column("conformity", sa.Float(), nullable=False),
        sa.Column("tradition", sa.Float(), nullable=False),
        sa.Column("benevolence", sa.Float(), nullable=False),
        sa.Column("universalism", sa.Float(), nullable=False),
        sa.Column(
            "analyzed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_source_schwartz_analysis_source_id"),
        "source_schwartz_analysis",
        ["source_id"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(
        op.f("ix_source_schwartz_analysis_source_id"),
        table_name="source_schwartz_analysis",
    )
    op.drop_table("source_schwartz_analysis")

    op.create_table(
        "post_schwartz_analysis",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("post_id", sa.BigInteger(), nullable=False),
        sa.Column("self_direction", sa.Float(), nullable=False),
        sa.Column("stimulation", sa.Float(), nullable=False),
        sa.Column("hedonism", sa.Float(), nullable=False),
        sa.Column("achievement", sa.Float(), nullable=False),
        sa.Column("power", sa.Float(), nullable=False),
        sa.Column("security", sa.Float(), nullable=False),
        sa.Column("conformity", sa.Float(), nullable=False),
        sa.Column("tradition", sa.Float(), nullable=False),
        sa.Column("benevolence", sa.Float(), nullable=False),
        sa.Column("universalism", sa.Float(), nullable=False),
        sa.Column(
            "analyzed_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["post_id"], ["posts.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        op.f("ix_post_schwartz_analysis_post_id"),
        "post_schwartz_analysis",
        ["post_id"],
        unique=True,
    )
