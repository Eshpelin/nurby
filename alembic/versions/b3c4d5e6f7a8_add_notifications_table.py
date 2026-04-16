"""add notifications table

Revision ID: b3c4d5e6f7a8
Revises: a2b3c4d5e6f7
Create Date: 2026-04-16 18:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = 'b3c4d5e6f7a8'
down_revision: Union[str, None] = 'a2b3c4d5e6f7'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        'notifications',
        sa.Column('id', postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column('message', sa.Text(), nullable=False),
        sa.Column('severity', sa.String(16), server_default='info'),
        sa.Column('rule_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('camera_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('observation_id', postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column('read', sa.Boolean(), server_default='false'),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.func.now()),
    )
    op.create_index('ix_notifications_rule_id', 'notifications', ['rule_id'])
    op.create_index('ix_notifications_camera_id', 'notifications', ['camera_id'])
    op.create_index('ix_notifications_read', 'notifications', ['read'])
    op.create_index('ix_notifications_created_at', 'notifications', ['created_at'])


def downgrade() -> None:
    op.drop_index('ix_notifications_created_at', table_name='notifications')
    op.drop_index('ix_notifications_read', table_name='notifications')
    op.drop_index('ix_notifications_camera_id', table_name='notifications')
    op.drop_index('ix_notifications_rule_id', table_name='notifications')
    op.drop_table('notifications')
