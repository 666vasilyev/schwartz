"""vozd: кэш результатов аналитики (последние рассчитанные значения метрик)

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-11-08
"""
from alembic import op
import sqlalchemy as sa

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vozd_analytics_cache",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("social_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_id", sa.String(16), nullable=False),
        sa.Column("window_key", sa.String(64), nullable=False, server_default="all"),
        sa.Column("status", sa.String(32), nullable=False),
        sa.Column("quality", sa.String(32), nullable=True),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("meta", sa.JSON(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("group_id", "metric_id", "window_key", name="uq_vozd_analytics_cache"),
    )
    op.create_index("ix_vozd_analytics_cache_group_id", "vozd_analytics_cache", ["group_id"])


def downgrade() -> None:
    op.drop_index("ix_vozd_analytics_cache_group_id", table_name="vozd_analytics_cache")
    op.drop_table("vozd_analytics_cache")
