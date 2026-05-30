"""sources: add telegram source_type (no-op — source_type is VARCHAR)

Revision ID: r6s7t8u9v0w1
Revises: q5r6s7t8u9v0
Create Date: 2026-05-30

source_type is stored as VARCHAR(32), so no DDL change is needed.
This migration is a checkpoint that records the intent.
"""
from alembic import op

revision = "r6s7t8u9v0w1"
down_revision = "q5r6s7t8u9v0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # source_type is VARCHAR(32) — 'telegram' is already a valid value.
    pass


def downgrade() -> None:
    op.execute(
        "UPDATE sources SET source_type = 'rss' WHERE source_type = 'telegram';"
    )
