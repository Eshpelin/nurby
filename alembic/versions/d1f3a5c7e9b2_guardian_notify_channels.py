"""guardian per-link notify channels

Revision ID: d1f3a5c7e9b2
Revises: c9e1f3a5b7d2
Create Date: 2026-06-07 13:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import JSON


revision: str = 'd1f3a5c7e9b2'
down_revision: Union[str, None] = 'c9e1f3a5b7d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("guardian_links", sa.Column("notify_channels", JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("guardian_links", "notify_channels")
