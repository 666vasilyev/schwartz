"""clustering: pgvector extension, embeddings, story clusters, assignments

Revision ID: l1m2n3o4p5q6
Revises: k1l2m3n4o5p6
Create Date: 2026-05-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector

revision: str = "l1m2n3o4p5q6"
down_revision: Union[str, None] = "k1l2m3n4o5p6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


# Размерность векторов должна совпадать с embedding_dim в core.config.
# Если решите сменить модель на другую размерность — нужна отдельная миграция.
EMBEDDING_DIM = 768


def upgrade() -> None:
    # 1. pgvector extension
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # 2. post_embeddings
    op.create_table(
        "post_embeddings",
        sa.Column(
            "post_id",
            sa.BigInteger(),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("embedding", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_post_embeddings_model_name",
        "post_embeddings",
        ["model_name"],
    )
    # HNSW индекс для cosine-расстояния (vector_cosine_ops).
    # m=16, ef_construction=64 — разумные дефолты pgvector.
    op.execute(
        "CREATE INDEX ix_post_embeddings_hnsw_cosine "
        "ON post_embeddings USING hnsw (embedding vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # 3. story_clusters
    op.create_table(
        "story_clusters",
        sa.Column("id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("centroid", Vector(EMBEDDING_DIM), nullable=False),
        sa.Column("model_name", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=512), nullable=True),
        sa.Column("summary", sa.Text(), nullable=True),
        sa.Column("topics", sa.JSON(), nullable=True),
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=False,
            server_default="active",
        ),
        sa.Column("posts_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sources_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "first_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "last_seen_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column("labels_updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index("ix_story_clusters_status", "story_clusters", ["status"])
    op.create_index(
        "ix_story_clusters_first_seen_at", "story_clusters", ["first_seen_at"]
    )
    op.create_index(
        "ix_story_clusters_last_seen_at", "story_clusters", ["last_seen_at"]
    )
    op.create_index(
        "ix_story_clusters_status_last_seen",
        "story_clusters",
        ["status", "last_seen_at"],
    )
    op.execute(
        "CREATE INDEX ix_story_clusters_centroid_hnsw_cosine "
        "ON story_clusters USING hnsw (centroid vector_cosine_ops) "
        "WITH (m = 16, ef_construction = 64)"
    )

    # 4. post_cluster_assignments
    op.create_table(
        "post_cluster_assignments",
        sa.Column(
            "post_id",
            sa.BigInteger(),
            sa.ForeignKey("posts.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column(
            "cluster_id",
            sa.BigInteger(),
            sa.ForeignKey("story_clusters.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("similarity", sa.Float(), nullable=False),
        sa.Column(
            "assigned_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
    )
    op.create_index(
        "ix_pca_cluster_id", "post_cluster_assignments", ["cluster_id"]
    )
    op.create_index(
        "ix_pca_cluster_id_assigned_at",
        "post_cluster_assignments",
        ["cluster_id", "assigned_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_pca_cluster_id_assigned_at", table_name="post_cluster_assignments"
    )
    op.drop_index("ix_pca_cluster_id", table_name="post_cluster_assignments")
    op.drop_table("post_cluster_assignments")

    op.execute("DROP INDEX IF EXISTS ix_story_clusters_centroid_hnsw_cosine")
    op.drop_index("ix_story_clusters_status_last_seen", table_name="story_clusters")
    op.drop_index("ix_story_clusters_last_seen_at", table_name="story_clusters")
    op.drop_index("ix_story_clusters_first_seen_at", table_name="story_clusters")
    op.drop_index("ix_story_clusters_status", table_name="story_clusters")
    op.drop_table("story_clusters")

    op.execute("DROP INDEX IF EXISTS ix_post_embeddings_hnsw_cosine")
    op.drop_index("ix_post_embeddings_model_name", table_name="post_embeddings")
    op.drop_table("post_embeddings")

    # CREATE EXTENSION оставляем — она безопасна и могла быть использована вне миграций.
