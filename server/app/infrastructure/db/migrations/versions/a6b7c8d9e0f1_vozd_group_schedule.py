"""vozd: расписание автосбора социальных групп

Revision ID: a6b7c8d9e0f1
Revises: z5a6b7c8d9e0
Create Date: 2026-11-04
"""
from alembic import op
import sqlalchemy as sa

revision = "a6b7c8d9e0f1"
down_revision = "z5a6b7c8d9e0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("social_groups", sa.Column("schedule_enabled", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("social_groups", sa.Column("schedule_interval_hours", sa.Integer(), nullable=False, server_default=sa.text("24")))
    op.add_column("social_groups", sa.Column("next_run_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("social_groups", sa.Column("last_scheduled_run_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("ix_social_groups_next_run_at", "social_groups", ["next_run_at"])


def downgrade() -> None:
    op.drop_index("ix_social_groups_next_run_at", table_name="social_groups")
    op.drop_column("social_groups", "last_scheduled_run_at")
    op.drop_column("social_groups", "next_run_at")
    op.drop_column("social_groups", "schedule_interval_hours")
    op.drop_column("social_groups", "schedule_enabled")
