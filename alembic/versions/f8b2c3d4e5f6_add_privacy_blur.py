"""add privacy blur

Revision ID: f8b2c3d4e5f6
Revises: e7a1b2c3d4e5
Create Date: 2026-04-18 13:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'f8b2c3d4e5f6'
down_revision: Union[str, None] = 'e7a1b2c3d4e5'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Per-person flag. When true, all recordings that include this person
    # get their face + body region blurred during post-processing.
    op.add_column(
        "persons",
        sa.Column("privacy_blur", sa.Boolean(), nullable=False, server_default=sa.false()),
    )

    # Track blur pass lifecycle per recording.
    op.add_column(
        "recordings",
        sa.Column("blur_status", sa.String(16), nullable=False, server_default="pending"),
    )
    op.add_column(
        "recordings",
        sa.Column("blur_error", sa.String(512), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("recordings", "blur_error")
    op.drop_column("recordings", "blur_status")
    op.drop_column("persons", "privacy_blur")
