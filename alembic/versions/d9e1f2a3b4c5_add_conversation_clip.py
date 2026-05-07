"""add clip_path + clip_duration_ms on conversations

Revision ID: d9e1f2a3b4c5
Revises: c8d9e1f2a3b4
Create Date: 2026-05-07 19:00:00.000000

When a conversation finalizes and the camera has overlapping
recordings on disk, the conversation finalizer slices out a single
mp4 covering the conversation window. The path lives on the
conversation row so the UI can render an inline video player without
a separate join.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "d9e1f2a3b4c5"
down_revision: Union[str, None] = "c8d9e1f2a3b4"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("clip_path", sa.String(1024), nullable=True))
    op.add_column("conversations", sa.Column("clip_duration_ms", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "clip_duration_ms")
    op.drop_column("conversations", "clip_path")
