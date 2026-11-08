"""vozd: аналитика групп (экспертные оценки, кэш результатов, снимки численности)

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f1
Create Date: 2026-11-08
"""
from alembic import op
import sqlalchemy as sa

revision = "b7c8d9e0f1a2"
down_revision = "a6b7c8d9e0f1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "vozd_analytics_expert",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("social_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_id", sa.String(16), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("justification", sa.Text(), nullable=True),
        sa.Column("expert", sa.String(255), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("group_id", "metric_id", name="uq_vozd_analytics_expert"),
    )
    op.create_index("ix_vozd_analytics_expert_group_id", "vozd_analytics_expert", ["group_id"])
    op.create_table(
        "vozd_analytics_results",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("social_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("metric_id", sa.String(16), nullable=False),
        sa.Column("params_key", sa.String(64), nullable=False),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("computed_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.UniqueConstraint("group_id", "metric_id", "params_key", name="uq_vozd_analytics_results"),
    )
    op.create_index("ix_vozd_analytics_results_group_id", "vozd_analytics_results", ["group_id"])
    op.create_table(
        "vozd_member_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("social_groups.id", ondelete="CASCADE"), nullable=False),
        sa.Column("source_id", sa.Integer(), sa.ForeignKey("sources.id", ondelete="CASCADE"), nullable=False),
        sa.Column("members_count", sa.BigInteger(), nullable=False),
        sa.Column("captured_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index("ix_vozd_member_snapshots_group_time", "vozd_member_snapshots", ["group_id", "captured_at"])


def downgrade() -> None:
    op.drop_index("ix_vozd_member_snapshots_group_time", table_name="vozd_member_snapshots")
    op.drop_table("vozd_member_snapshots")
    op.drop_index("ix_vozd_analytics_results_group_id", table_name="vozd_analytics_results")
    op.drop_table("vozd_analytics_results")
    op.drop_index("ix_vozd_analytics_expert_group_id", table_name="vozd_analytics_expert")
    op.drop_table("vozd_analytics_expert")
