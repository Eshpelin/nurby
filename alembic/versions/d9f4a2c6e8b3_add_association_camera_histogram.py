"""where an association usually happens

Revision ID: d9f4a2c6e8b3
Revises: c8e2b5d7f3a1
Create Date: 2026-08-24 17:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'd9f4a2c6e8b3'
down_revision: Union[str, None] = 'c8e2b5d7f3a1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # "Someone else is parked in your spot" is a claim about a place, so
    # the edge has to remember where it usually happens, not only when.
    op.add_column(
        "entity_associations",
        sa.Column("camera_histogram", sa.JSON(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("entity_associations", "camera_histogram")
