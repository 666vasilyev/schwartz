"""sources: drop platform and source columns, normalize source_type values

Revision ID: p4q5r6s7t8u9
Revises: o3p4q5r6s7t8
Create Date: 2026-05-30
"""
from alembic import op
import sqlalchemy as sa

revision = "p4q5r6s7t8u9"
down_revision = "o3p4q5r6s7t8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Normalize source_type: collapse vk_group/vk_public → vk
    op.execute("UPDATE sources SET source_type = 'vk' WHERE source_type IN ('vk_group', 'vk_public')")

    # Drop old unique indexes that used platform column
    op.drop_index("uq_sources_platform_external_id", table_name="sources", if_exists=True)
    op.drop_index("uq_sources_platform_username", table_name="sources", if_exists=True)
    op.drop_index("ix_sources_platform", table_name="sources", if_exists=True)
    op.drop_index("ix_sources_source", table_name="sources", if_exists=True)

    # Drop the columns
    op.drop_column("sources", "platform")
    op.drop_column("sources", "source")

    # Create new unique indexes using source_type
    op.create_index(
        "uq_sources_source_type_external_id",
        "sources",
        ["source_type", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_sources_source_type_username",
        "sources",
        ["source_type", "username"],
        unique=True,
        postgresql_where=sa.text("username IS NOT NULL AND deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_sources_source_type_external_id", table_name="sources", if_exists=True)
    op.drop_index("uq_sources_source_type_username", table_name="sources", if_exists=True)

    op.add_column("sources", sa.Column("platform", sa.String(32), nullable=True))
    op.add_column("sources", sa.Column("source", sa.String(32), nullable=True, server_default="vk"))

    op.execute("UPDATE sources SET platform = source_type, source = CASE WHEN source_type = 'rss' THEN 'rss' ELSE 'vk' END")

    op.create_index("ix_sources_platform", "sources", ["platform"])
    op.create_index("ix_sources_source", "sources", ["source"])
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
