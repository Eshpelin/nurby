"""add observations.clean_frame_path (grounding on clean pixels)

Revision ID: a3f5c1e9d7b2
Revises: f1a3c5e7b9d2
Create Date: 2026-06-23 00:00:00.000000

A clean keyframe path (no detection boxes burned in) so FindAnything grounds on
real pixels rather than a drawn rectangle. Null falls back to thumbnail_path.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a3f5c1e9d7b2"
down_revision: Union[str, None] = "f1a3c5e7b9d2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "observations",
        sa.Column("clean_frame_path", sa.String(length=1024), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("observations", "clean_frame_path")
