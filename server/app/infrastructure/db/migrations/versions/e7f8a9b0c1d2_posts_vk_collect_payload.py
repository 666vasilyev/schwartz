"""posts.payload — расширенные данные collect (VK)

Revision ID: e7f8a9b0c1d2
Revises: c9a8b7c6d5e4
Create Date: 2026-04-27

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "e7f8a9b0c1d2"
down_revision: Union[str, Sequence[str], None] = "c9a8b7c6d5e4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("posts", sa.Column("payload", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("posts", "payload")
