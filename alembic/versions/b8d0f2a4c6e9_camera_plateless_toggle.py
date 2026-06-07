"""per-camera plateless vehicle re-id toggle

Revision ID: b8d0f2a4c6e9
Revises: a7c9e1b3d5f8
Create Date: 2026-06-06 15:30:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'b8d0f2a4c6e9'
down_revision: Union[str, None] = 'a7c9e1b3d5f8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable tri-state. None = auto (on unless outdoor).
    op.add_column(
        "cameras",
        sa.Column("plateless_reid_enabled", sa.Boolean(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("cameras", "plateless_reid_enabled")
