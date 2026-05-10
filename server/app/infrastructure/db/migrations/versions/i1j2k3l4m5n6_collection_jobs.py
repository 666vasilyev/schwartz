"""collection_jobs: job queue, logs, dead-letter queue

Revision ID: i1j2k3l4m5n6
Revises: h1i2j3k4l5m6
Create Date: 2026-05-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "i1j2k3l4m5n6"
down_revision: Union[str, Sequence[str], None] = "h1i2j3k4l5m6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── collection_jobs ────────────────────────────────────────────────────
    op.create_table(
        "collection_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("status", sa.String(32), nullable=False, server_default="created"),
        sa.Column("trigger_type", sa.String(32), nullable=False, server_default="manual"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("requested_limit", sa.Integer(), nullable=True),
        sa.Column("fetched_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("saved_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("duplicate_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("skipped_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("failed_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("worker_id", sa.String(128), nullable=True),
        sa.Column("correlation_id", sa.String(128), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_retries", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("timeout_seconds", sa.Integer(), nullable=False, server_default="300"),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collection_jobs_source_id", "collection_jobs", ["source_id"])
    op.create_index("ix_collection_jobs_status", "collection_jobs", ["status"])
    op.create_index("ix_collection_jobs_job_type", "collection_jobs", ["job_type"])
    op.create_index("ix_collection_jobs_worker_id", "collection_jobs", ["worker_id"])
    op.create_index("ix_collection_jobs_correlation_id", "collection_jobs", ["correlation_id"])
    # Composite index for queue polling: queued jobs by priority + created_at
    op.create_index(
        "ix_collection_jobs_queue",
        "collection_jobs",
        ["status", "priority", "created_at"],
    )

    # ── collection_job_logs ────────────────────────────────────────────────
    op.create_table(
        "collection_job_logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_id", sa.Integer(), nullable=False),
        sa.Column("level", sa.String(16), nullable=False, server_default="info"),
        sa.Column("message", sa.Text(), nullable=False),
        sa.Column("data", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(["job_id"], ["collection_jobs.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_collection_job_logs_job_id", "collection_job_logs", ["job_id"])

    # ── dead_letter_jobs ───────────────────────────────────────────────────
    op.create_table(
        "dead_letter_jobs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("original_job_id", sa.Integer(), nullable=True),
        sa.Column("source_id", sa.Integer(), nullable=True),
        sa.Column("job_type", sa.String(32), nullable=False),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "dead_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["original_job_id"], ["collection_jobs.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_dead_letter_jobs_original_job_id", "dead_letter_jobs", ["original_job_id"])
    op.create_index("ix_dead_letter_jobs_source_id", "dead_letter_jobs", ["source_id"])


def downgrade() -> None:
    op.drop_index("ix_dead_letter_jobs_source_id", table_name="dead_letter_jobs")
    op.drop_index("ix_dead_letter_jobs_original_job_id", table_name="dead_letter_jobs")
    op.drop_table("dead_letter_jobs")

    op.drop_index("ix_collection_job_logs_job_id", table_name="collection_job_logs")
    op.drop_table("collection_job_logs")

    op.drop_index("ix_collection_jobs_queue", table_name="collection_jobs")
    op.drop_index("ix_collection_jobs_correlation_id", table_name="collection_jobs")
    op.drop_index("ix_collection_jobs_worker_id", table_name="collection_jobs")
    op.drop_index("ix_collection_jobs_job_type", table_name="collection_jobs")
    op.drop_index("ix_collection_jobs_status", table_name="collection_jobs")
    op.drop_index("ix_collection_jobs_source_id", table_name="collection_jobs")
    op.drop_table("collection_jobs")
