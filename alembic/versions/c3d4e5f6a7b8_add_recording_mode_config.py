"""add recording mode config

Revision ID: c3d4e5f6a7b8
Revises: b7e8f9a0c1d2
Create Date: 2026-04-16 18:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c3d4e5f6a7b8'
down_revision: Union[str, None] = 'b7e8f9a0c1d2'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('cameras', sa.Column('recording_mode', sa.String(length=16), nullable=False, server_default='always'))
    op.add_column('cameras', sa.Column('recording_trigger_objects', sa.JSON(), nullable=True))
    op.add_column('cameras', sa.Column('recording_clip_pre', sa.Integer(), nullable=False, server_default='5'))
    op.add_column('cameras', sa.Column('recording_clip_post', sa.Integer(), nullable=False, server_default='10'))


def downgrade() -> None:
    op.drop_column('cameras', 'recording_clip_post')
    op.drop_column('cameras', 'recording_clip_pre')
    op.drop_column('cameras', 'recording_trigger_objects')
    op.drop_column('cameras', 'recording_mode')
