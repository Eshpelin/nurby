"""add event action tracking columns

Revision ID: a3b4c5d6e7f8
Revises: 936b67ae5404
Create Date: 2026-04-16 14:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a3b4c5d6e7f8'
down_revision: Union[str, None] = '936b67ae5404'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column('events', sa.Column('action_status', sa.String(length=16), nullable=False, server_default='pending'))
    op.add_column('events', sa.Column('action_error', sa.Text(), nullable=True))
    op.add_column('events', sa.Column('action_type', sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column('events', 'action_type')
    op.drop_column('events', 'action_error')
    op.drop_column('events', 'action_status')
