"""add missing indexes on foreign keys

Revision ID: 5ac1155eecd0
Revises: c4057c8154c0
Create Date: 2026-04-18 01:40:17.677663
"""

from typing import Sequence, Union

from alembic import op

revision: str = '5ac1155eecd0'
down_revision: Union[str, None] = 'c4057c8154c0'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(op.f('ix_cameras_vlm_provider_id'), 'cameras', ['vlm_provider_id'], unique=False)
    op.create_index(op.f('ix_cameras_digest_provider_id'), 'cameras', ['digest_provider_id'], unique=False)
    op.create_index(op.f('ix_face_clusters_person_id'), 'face_clusters', ['person_id'], unique=False)
    op.create_index(op.f('ix_invite_keys_created_by_id'), 'invite_keys', ['created_by_id'], unique=False)
    op.create_index(op.f('ix_user_camera_access_user_id'), 'user_camera_access', ['user_id'], unique=False)
    op.create_index(op.f('ix_user_camera_access_camera_id'), 'user_camera_access', ['camera_id'], unique=False)
    op.create_index(op.f('ix_user_camera_access_granted_by_id'), 'user_camera_access', ['granted_by_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_user_camera_access_granted_by_id'), table_name='user_camera_access')
    op.drop_index(op.f('ix_user_camera_access_camera_id'), table_name='user_camera_access')
    op.drop_index(op.f('ix_user_camera_access_user_id'), table_name='user_camera_access')
    op.drop_index(op.f('ix_invite_keys_created_by_id'), table_name='invite_keys')
    op.drop_index(op.f('ix_face_clusters_person_id'), table_name='face_clusters')
    op.drop_index(op.f('ix_cameras_digest_provider_id'), table_name='cameras')
    op.drop_index(op.f('ix_cameras_vlm_provider_id'), table_name='cameras')
