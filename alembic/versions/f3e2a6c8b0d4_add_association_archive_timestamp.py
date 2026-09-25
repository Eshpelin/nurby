"""track when learned associations are archived for staleness

Revision ID: f3e2a6c8b0d4
Revises: f3d1a5c7e9b2
Create Date: 2026-09-26 00:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "f3e2a6c8b0d4"
down_revision: Union[str, None] = "f3d1a5c7e9b2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("entity_associations", sa.Column("archived_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("entity_associations", "archived_at")
