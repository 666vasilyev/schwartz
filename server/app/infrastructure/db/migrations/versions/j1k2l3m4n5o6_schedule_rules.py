"""schedule_rules: ScheduleRule, ScheduleLog, schedule_group on sources

Revision ID: j1k2l3m4n5o6
Revises: i1j2k3l4m5n6
Create Date: 2026-05-10

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "j1k2l3m4n5o6"
down_revision: Union[str, Sequence[str], None] = "i1j2k3l4m5n6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── schedule_group column on sources ──────────────────────────────────
    op.add_column("sources", sa.Column("schedule_group", sa.String(128), nullable=True))
    op.create_index("ix_sources_schedule_group", "sources", ["schedule_group"])

    # ── schedule_rules ─────────────────────────────────────────────────────
    op.create_table(
        "schedule_rules",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("rule_type", sa.String(32), nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("platform", sa.String(32), nullable=True),
        sa.Column("group_name", sa.String(128), nullable=True),
        sa.Column("base_interval_minutes", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("min_interval_minutes", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("max_interval_minutes", sa.Integer(), nullable=False, server_default="10080"),
        sa.Column("error_backoff_multiplier", sa.Float(), nullable=False, server_default="1.5"),
        sa.Column("max_error_backoff_minutes", sa.Integer(), nullable=False, server_default="480"),
        sa.Column("priority_boost_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("night_mode_enabled", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("night_start_hour", sa.Integer(), nullable=False, server_default="23"),
        sa.Column("night_end_hour", sa.Integer(), nullable=False, server_default="7"),
        sa.Column("night_interval_minutes", sa.Integer(), nullable=False, server_default="360"),
        sa.Column("max_jobs_per_hour", sa.Integer(), nullable=False, server_default="60"),
        sa.Column("max_concurrent_jobs", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default="true"),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="CASCADE"),
    )
    op.create_index("ix_schedule_rules_rule_type", "schedule_rules", ["rule_type"])
    op.create_index("ix_schedule_rules_source_id", "schedule_rules", ["source_id"])
    op.create_index("ix_schedule_rules_platform", "schedule_rules", ["platform"])
    op.create_index("ix_schedule_rules_group_name", "schedule_rules", ["group_name"])
    op.create_index("ix_schedule_rules_is_enabled", "schedule_rules", ["is_enabled"])

    # ── schedule_logs ──────────────────────────────────────────────────────
    op.create_table(
        "schedule_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("rule_id", sa.Integer(), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("trigger_reason", sa.String(64), nullable=False, server_default="scheduled"),
        sa.Column("calculated_interval_minutes", sa.Float(), nullable=True),
        sa.Column("next_fetch_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fired_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id"),
        sa.ForeignKeyConstraint(["rule_id"], ["schedule_rules.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="SET NULL"),
        sa.ForeignKeyConstraint(["job_id"], ["collection_jobs.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_schedule_logs_rule_id", "schedule_logs", ["rule_id"])
    op.create_index("ix_schedule_logs_source_id", "schedule_logs", ["source_id"])
    op.create_index("ix_schedule_logs_fired_at", "schedule_logs", ["fired_at"])


def downgrade() -> None:
    op.drop_table("schedule_logs")
    op.drop_table("schedule_rules")
    op.drop_index("ix_sources_schedule_group", "sources")
    op.drop_column("sources", "schedule_group")
