"""sources_v2: new fields, SourceType enum, updated SourceStatus, soft-delete, audit log

Revision ID: h1i2j3k4l5m6
Revises: g2h3i4j5k6l7
Create Date: 2026-05-10

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "h1i2j3k4l5m6"
down_revision: Union[str, Sequence[str], None] = "g2h3i4j5k6l7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # ── Migrate existing status values to new enum ─────────────────────────
    op.execute("""
        UPDATE sources SET status = 'active'
        WHERE status IN ('idle', 'running', 'ok', 'warning')
    """)

    # ── New columns on sources ─────────────────────────────────────────────
    op.add_column("sources", sa.Column("source_type", sa.String(32), nullable=True))
    op.add_column("sources", sa.Column("platform", sa.String(32), nullable=True))
    op.add_column("sources", sa.Column("username", sa.String(255), nullable=True))
    op.add_column("sources", sa.Column("external_id", sa.String(512), nullable=True))
    op.add_column("sources", sa.Column("description", sa.Text(), nullable=True))
    op.add_column(
        "sources",
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sources",
        sa.Column("fetch_interval_minutes", sa.Integer(), nullable=False, server_default="60"),
    )
    op.add_column("sources", sa.Column("last_fetch_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("sources", sa.Column("next_fetch_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "sources", sa.Column("last_success_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column("sources", sa.Column("last_error_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column(
        "sources",
        sa.Column("error_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "sources",
        sa.Column("auth_required", sa.Boolean(), nullable=False, server_default="false"),
    )
    op.add_column("sources", sa.Column("collection_policy", sa.JSON(), nullable=True))
    op.add_column("sources", sa.Column("content_policy", sa.JSON(), nullable=True))
    op.add_column("sources", sa.Column("media_policy", sa.JSON(), nullable=True))
    op.add_column("sources", sa.Column("language_hint", sa.String(16), nullable=True))
    op.add_column("sources", sa.Column("region_hint", sa.String(64), nullable=True))
    op.add_column("sources", sa.Column("topic_hint", sa.String(255), nullable=True))
    op.add_column("sources", sa.Column("owner_id", sa.Integer(), nullable=True))
    op.add_column("sources", sa.Column("metadata", sa.JSON(), nullable=True))
    op.add_column("sources", sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True))

    # Back-fill platform / source_type from legacy `source` column
    op.execute("""
        UPDATE sources
        SET platform = source,
            source_type = CASE source
                WHEN 'vk'  THEN 'vk_public'
                WHEN 'rss' THEN 'rss'
                ELSE source
            END
        WHERE platform IS NULL
    """)
    # Back-fill external_id from vk_owner_id
    op.execute("""
        UPDATE sources
        SET external_id = vk_owner_id::text
        WHERE vk_owner_id IS NOT NULL AND external_id IS NULL
    """)

    # ── Deduplicate before creating unique indexes ─────────────────────────
    # Keep the row with the smallest id for each (platform, external_id) pair;
    # soft-delete the rest so the unique partial index can be created cleanly.
    op.execute("""
        UPDATE sources
        SET deleted_at = now(),
            status     = 'deleted'
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM sources
            WHERE external_id IS NOT NULL
            GROUP BY platform, external_id
        )
        AND external_id IS NOT NULL
        AND deleted_at IS NULL
    """)
    # Same deduplication for (platform, username)
    op.execute("""
        UPDATE sources
        SET deleted_at = now(),
            status     = 'deleted'
        WHERE id NOT IN (
            SELECT MIN(id)
            FROM sources
            WHERE username IS NOT NULL
            GROUP BY platform, username
        )
        AND username IS NOT NULL
        AND deleted_at IS NULL
    """)

    # ── Indexes on new columns ─────────────────────────────────────────────
    op.create_index("ix_sources_source_type", "sources", ["source_type"], unique=False)
    op.create_index("ix_sources_platform", "sources", ["platform"], unique=False)
    op.create_index("ix_sources_owner_id", "sources", ["owner_id"], unique=False)

    # Partial unique indexes (NULL values are excluded automatically)
    op.create_index(
        "uq_sources_platform_external_id",
        "sources",
        ["platform", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_sources_platform_username",
        "sources",
        ["platform", "username"],
        unique=True,
        postgresql_where=sa.text("username IS NOT NULL AND deleted_at IS NULL"),
    )

    # ── Audit log table ────────────────────────────────────────────────────
    op.create_table(
        "source_audit_logs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("actor_id", sa.Integer(), nullable=True),
        sa.Column("previous", sa.JSON(), nullable=True),
        sa.Column("changes", sa.JSON(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.ForeignKeyConstraint(
            ["source_id"],
            ["sources.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_source_audit_logs_source_id", "source_audit_logs", ["source_id"], unique=False
    )
    op.create_index(
        "ix_source_audit_logs_action", "source_audit_logs", ["action"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_source_audit_logs_action", table_name="source_audit_logs")
    op.drop_index("ix_source_audit_logs_source_id", table_name="source_audit_logs")
    op.drop_table("source_audit_logs")

    op.drop_index("uq_sources_platform_username", table_name="sources")
    op.drop_index("uq_sources_platform_external_id", table_name="sources")
    op.drop_index("ix_sources_owner_id", table_name="sources")
    op.drop_index("ix_sources_platform", table_name="sources")
    op.drop_index("ix_sources_source_type", table_name="sources")

    for col in [
        "deleted_at", "metadata", "owner_id", "topic_hint", "region_hint", "language_hint",
        "media_policy", "content_policy", "collection_policy", "auth_required",
        "error_count", "last_error_at", "last_success_at", "next_fetch_at", "last_fetch_at",
        "fetch_interval_minutes", "priority", "description", "external_id", "username",
        "platform", "source_type",
    ]:
        op.drop_column("sources", col)

    # Restore legacy status values: map unknown back to idle
    op.execute("""
        UPDATE sources SET status = 'idle'
        WHERE status NOT IN ('idle', 'running', 'ok', 'warning', 'error', 'paused')
    """)
