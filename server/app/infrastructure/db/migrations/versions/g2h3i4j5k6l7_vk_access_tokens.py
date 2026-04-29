"""vk_access_tokens: токены VK + usage для выбора наименее нагруженного

Revision ID: g2h3i4j5k6l7
Revises: f1a2b3c4d5e6
Create Date: 2026-04-28

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "g2h3i4j5k6l7"
down_revision: Union[str, Sequence[str], None] = "f1a2b3c4d5e6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "vk_access_tokens",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("access_token", sa.Text(), nullable=False),
        sa.Column(
            "usage",
            sa.BigInteger(),
            server_default="0",
            nullable=False,
        ),
        sa.Column("last_used_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            server_default="true",
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_vk_access_tokens_usage",
        "vk_access_tokens",
        ["usage"],
        unique=False,
    )
    op.create_index(
        "ix_vk_access_tokens_active",
        "vk_access_tokens",
        ["is_active"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_vk_access_tokens_active", table_name="vk_access_tokens")
    op.drop_index("ix_vk_access_tokens_usage", table_name="vk_access_tokens")
    op.drop_table("vk_access_tokens")
