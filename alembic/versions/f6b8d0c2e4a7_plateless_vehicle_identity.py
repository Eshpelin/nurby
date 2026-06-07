"""plateless vehicle appearance identity

Revision ID: f6b8d0c2e4a7
Revises: e5a7c9b1d3f6
Create Date: 2026-06-06 14:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import Vector


revision: str = 'f6b8d0c2e4a7'
down_revision: Union[str, None] = 'e5a7c9b1d3f6'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "vehicles",
        sa.Column("plateless", sa.Boolean(), server_default=sa.false(), nullable=False),
    )
    op.add_column(
        "vehicles",
        sa.Column("appearance_embedding", Vector(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("vehicles", "appearance_embedding")
    op.drop_column("vehicles", "plateless")
