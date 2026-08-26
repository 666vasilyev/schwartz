"""lemma buffer: drop times_selected, add weights/category

Revision ID: w2x3y4z5a6b7
Revises: v0w1x2y3z4a5
Create Date: 2026-08-26
"""
from alembic import op
import sqlalchemy as sa

revision = "w2x3y4z5a6b7"
down_revision = "v0w1x2y3z4a5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("lemma_buffer_entries", sa.Column("weights", sa.JSON(), nullable=True))
    op.add_column("lemma_buffer_entries", sa.Column("category", sa.String(512), nullable=True))
    op.drop_column("lemma_buffer_entries", "times_selected")


def downgrade() -> None:
    op.add_column(
        "lemma_buffer_entries",
        sa.Column("times_selected", sa.Integer(), nullable=False, server_default="1"),
    )
    op.drop_column("lemma_buffer_entries", "category")
    op.drop_column("lemma_buffer_entries", "weights")
