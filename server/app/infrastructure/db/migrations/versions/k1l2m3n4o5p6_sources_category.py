"""sources: add category column (ru_smi, ua_smi, foreign_smi)

Revision ID: k1l2m3n4o5p6
Revises: j1k2l3m4n5o6
Create Date: 2026-05-28

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "k1l2m3n4o5p6"
down_revision: Union[str, None] = "j1k2l3m4n5o6"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "sources",
        sa.Column("category", sa.String(32), nullable=True),
    )
    op.create_index("ix_sources_category", "sources", ["category"])


def downgrade() -> None:
    op.drop_index("ix_sources_category", table_name="sources")
    op.drop_column("sources", "category")
