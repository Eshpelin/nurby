"""add smart-track PTZ fields to cameras

Revision ID. b5c6d7e8f9a2
Revises. a3b4c5d9e1f2
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "b5c6d7e8f9a2"
down_revision: Union[str, None] = "a3b4c5d9e1f2"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("cameras", sa.Column("ptz_smart_track_enabled", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("cameras", sa.Column("ptz_smart_track_targets", sa.JSON(), nullable=True))
    op.add_column("cameras", sa.Column("ptz_smart_track_ignore", sa.JSON(), nullable=True))
    op.add_column("cameras", sa.Column("ptz_smart_track_priority", sa.JSON(), nullable=True))
    op.add_column("cameras", sa.Column("ptz_smart_track_lost_seconds", sa.Integer(), nullable=False, server_default="3"))
    op.add_column("cameras", sa.Column("ptz_smart_track_home_preset", sa.String(length=64), nullable=True))
    op.add_column("cameras", sa.Column("ptz_smart_track_zoom", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("cameras", sa.Column("ptz_smart_track_deadzone", sa.Float(), nullable=False, server_default="0.15"))
    op.add_column("cameras", sa.Column("ptz_smart_track_max_speed", sa.Float(), nullable=False, server_default="0.5"))
    op.add_column("cameras", sa.Column("ptz_smart_track_gain", sa.Float(), nullable=False, server_default="1.5"))
    op.add_column("cameras", sa.Column("ptz_smart_track_no_go", sa.JSON(), nullable=True))
    op.add_column("cameras", sa.Column("ptz_smart_track_min_confidence", sa.Float(), nullable=False, server_default="0.45"))
    op.add_column("cameras", sa.Column("ptz_smart_track_require_face", sa.JSON(), nullable=True))
    op.add_column("cameras", sa.Column("ptz_smart_track_move_budget_per_minute", sa.Integer(), nullable=False, server_default="30"))
    op.add_column("cameras", sa.Column("ptz_profile_token", sa.String(length=64), nullable=False, server_default="Profile_1"))


def downgrade() -> None:
    for col in [
        "ptz_profile_token",
        "ptz_smart_track_move_budget_per_minute",
        "ptz_smart_track_require_face",
        "ptz_smart_track_min_confidence",
        "ptz_smart_track_no_go",
        "ptz_smart_track_gain",
        "ptz_smart_track_max_speed",
        "ptz_smart_track_deadzone",
        "ptz_smart_track_zoom",
        "ptz_smart_track_home_preset",
        "ptz_smart_track_lost_seconds",
        "ptz_smart_track_priority",
        "ptz_smart_track_ignore",
        "ptz_smart_track_targets",
        "ptz_smart_track_enabled",
    ]:
        op.drop_column("cameras", col)
