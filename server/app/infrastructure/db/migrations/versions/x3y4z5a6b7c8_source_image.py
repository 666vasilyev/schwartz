"""sources: image_filename / image_updated_at

Revision ID: x3y4z5a6b7c8
Revises: w2x3y4z5a6b7
Create Date: 2026-09-28
"""
from alembic import op
import sqlalchemy as sa

revision = "x3y4z5a6b7c8"
down_revision = "w2x3y4z5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("image_filename", sa.String(255), nullable=True))
    op.add_column("sources", sa.Column("image_updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("sources", "image_updated_at")
    op.drop_column("sources", "image_filename")
