"""native-audio conversation analysis columns

Revision ID: a7c9e1b3d5f8
Revises: f6b8d0c2e4a7
Create Date: 2026-06-06 15:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a7c9e1b3d5f8'
down_revision: Union[str, None] = 'f6b8d0c2e4a7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("conversations", sa.Column("audio_speaker_count", sa.Integer(), nullable=True))
    op.add_column("conversations", sa.Column("audio_tone", sa.String(length=16), nullable=True))
    op.add_column("conversations", sa.Column("audio_non_verbal", sa.JSON(), nullable=True))
    op.add_column("conversations", sa.Column("audio_gist", sa.Text(), nullable=True))
    op.add_column("conversations", sa.Column("audio_analyzed_by", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("conversations", "audio_analyzed_by")
    op.drop_column("conversations", "audio_gist")
    op.drop_column("conversations", "audio_non_verbal")
    op.drop_column("conversations", "audio_tone")
    op.drop_column("conversations", "audio_speaker_count")
