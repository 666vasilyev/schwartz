"""vozd: project flag + social groups, users, profile data, runs

Revision ID: x3y4z5a6b7c8
Revises: w2x3y4z5a6b7
Create Date: 2026-10-24
"""
from alembic import op
import sqlalchemy as sa

revision = "x3y4z5a6b7c8"
down_revision = "w2x3y4z5a6b7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # ── project flag: существующие строки автоматически получают 'wall' ──
    op.add_column(
        "sources",
        sa.Column("project", sa.String(32), nullable=False, server_default="wall"),
    )
    op.add_column(
        "posts",
        sa.Column("project", sa.String(32), nullable=False, server_default="wall"),
    )
    op.add_column(
        "posts",
        sa.Column("comments_collected_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_sources_project", "sources", ["project"])
    op.create_index("ix_posts_project", "posts", ["project"])
    op.create_index(
        "ix_posts_project_owner_vk_post", "posts", ["project", "owner_id", "vk_post_id"]
    )

    # Уникальность источников теперь в рамках проекта (для wall — как раньше).
    op.drop_index("uq_sources_source_type_external_id", table_name="sources")
    op.drop_index("uq_sources_source_type_username", table_name="sources")
    op.create_index(
        "uq_sources_project_source_type_external_id",
        "sources",
        ["project", "source_type", "external_id"],
        unique=True,
        postgresql_where=sa.text("external_id IS NOT NULL AND deleted_at IS NULL"),
    )
    op.create_index(
        "uq_sources_project_source_type_username",
        "sources",
        ["project", "source_type", "username"],
        unique=True,
        postgresql_where=sa.text("username IS NOT NULL AND deleted_at IS NULL"),
    )

    # ── social groups ──
    op.create_table(
        "social_groups",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index(
        "uq_social_groups_name",
        "social_groups",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_table(
        "social_group_sources",
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("social_groups.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "source_id",
            sa.Integer(),
            sa.ForeignKey("sources.id", ondelete="CASCADE"),
            primary_key=True,
        ),
    )
    op.create_index("ix_social_group_sources_source_id", "social_group_sources", ["source_id"])

    # ── users (участники обсуждений / авторы) ──
    op.create_table(
        "vozd_users",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("platform", sa.String(16), nullable=False),
        sa.Column("external_id", sa.BigInteger(), nullable=False),
        sa.Column("username", sa.String(255), nullable=True),
        sa.Column("first_name", sa.String(255), nullable=True),
        sa.Column("last_name", sa.String(255), nullable=True),
        sa.Column("about", sa.Text(), nullable=True),
        sa.Column("profile", sa.JSON(), nullable=True),
        # ok | closed | deleted | banned | unavailable | pending
        sa.Column("profile_status", sa.String(32), nullable=False, server_default="pending"),
        sa.Column("friends_status", sa.String(32), nullable=True),
        sa.Column("groups_status", sa.String(32), nullable=True),
        sa.Column("posts_status", sa.String(32), nullable=True),
        sa.Column("profile_error", sa.Text(), nullable=True),
        sa.Column("profile_collected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("platform", "external_id", name="uq_vozd_users_platform_external"),
    )
    op.create_index("ix_vozd_users_profile_collected_at", "vozd_users", ["profile_collected_at"])

    op.create_table(
        "vozd_user_groups",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("vozd_users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("group_external_id", sa.BigInteger(), primary_key=True),
        sa.Column("name", sa.String(512), nullable=True),
        sa.Column("screen_name", sa.String(255), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
    )
    op.create_table(
        "vozd_user_friends",
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("vozd_users.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("friend_external_id", sa.BigInteger(), primary_key=True),
    )
    op.create_table(
        "vozd_user_posts",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column(
            "user_id",
            sa.BigInteger(),
            sa.ForeignKey("vozd_users.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        sa.Column("owner_id", sa.BigInteger(), nullable=False),
        sa.Column("vk_post_id", sa.String(64), nullable=False),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("is_repost", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("repost_of", sa.JSON(), nullable=True),
        sa.Column("reactions", sa.JSON(), nullable=True),
        sa.UniqueConstraint("user_id", "owner_id", "vk_post_id", name="uq_vozd_user_posts"),
    )

    # ── прогон сбора с чекпойнтами ──
    op.create_table(
        "vozd_runs",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column(
            "group_id",
            sa.Integer(),
            sa.ForeignKey("social_groups.id", ondelete="CASCADE"),
            nullable=False,
            index=True,
        ),
        # queued | running | success | failed | cancelled
        sa.Column("status", sa.String(32), nullable=False, server_default="queued"),
        # posts | comments | profiles | done
        sa.Column("stage", sa.String(32), nullable=False, server_default="posts"),
        sa.Column("params", sa.JSON(), nullable=True),
        sa.Column("progress", sa.JSON(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_vozd_runs_status", "vozd_runs", ["status"])


def downgrade() -> None:
    op.drop_table("vozd_runs")
    op.drop_table("vozd_user_posts")
    op.drop_table("vozd_user_friends")
    op.drop_table("vozd_user_groups")
    op.drop_table("vozd_users")
    op.drop_table("social_group_sources")
    op.drop_table("social_groups")

    op.drop_index("uq_sources_project_source_type_username", table_name="sources")
    op.drop_index("uq_sources_project_source_type_external_id", table_name="sources")
    # Строки vozd несовместимы со старыми уникальными индексами — удаляем их перед откатом.
    op.execute("DELETE FROM posts WHERE project <> 'wall'")
    op.execute("DELETE FROM sources WHERE project <> 'wall'")
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
    op.drop_index("ix_posts_project_owner_vk_post", table_name="posts")
    op.drop_index("ix_posts_project", table_name="posts")
    op.drop_index("ix_sources_project", table_name="sources")
    op.drop_column("posts", "comments_collected_at")
    op.drop_column("posts", "project")
    op.drop_column("sources", "project")
