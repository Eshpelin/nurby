"""add motion_samples (downsampled per-camera motion-score series)

Revision ID: a4e6c8f0b2d5
Revises: f3a4b5c6d7e8
Create Date: 2026-06-17 00:00:00.000000

Persists a downsampled per-camera motion-score time series written from the
existing motion pipeline (perception keyframe path), backing the new
GET /cameras/{id}/motion endpoint (#37). Each row is one 1-second bucket
holding the peak motion score (0..1) for that camera-second. A unique
constraint on (camera_id, bucket) is the upsert target that coalesces
sub-second frames to one row keeping the max score, bounding write volume.
The composite index serves the (camera_id, time-window) range scans the
read endpoint issues.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a4e6c8f0b2d5"
down_revision: Union[str, None] = "f3a4b5c6d7e8"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "motion_samples",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("camera_id", sa.UUID(), nullable=False),
        sa.Column("bucket", sa.DateTime(timezone=True), nullable=False),
        sa.Column("score", sa.Float(), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("camera_id", "bucket", name="uq_motion_samples_camera_bucket"),
    )
    op.create_index(
        "ix_motion_samples_camera_bucket",
        "motion_samples",
        ["camera_id", "bucket"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_motion_samples_camera_bucket", table_name="motion_samples")
    op.drop_table("motion_samples")
