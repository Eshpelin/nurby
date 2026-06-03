"""add user is_provisional

Revision ID: a1c3e5f7b9d2
Revises: f2a4c6e8b1d3
Create Date: 2026-06-03 09:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a1c3e5f7b9d2'
down_revision: Union[str, None] = 'f2a4c6e8b1d3'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Auto-created first-run owner that has not set real credentials yet.
    # Drives the "Secure your account" prompt until claimed.
    op.add_column(
        "users",
        sa.Column(
            "is_provisional",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "is_provisional")
