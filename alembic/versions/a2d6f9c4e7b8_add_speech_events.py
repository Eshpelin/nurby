"""camera speaker settings and the speech audit trail

Revision ID: a2d6f9c4e7b8
Revises: f4b8c2e6a9d1
Create Date: 2026-08-29 11:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'a2d6f9c4e7b8'
down_revision: Union[str, None] = 'f4b8c2e6a9d1'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Speaking is opt-in per camera even once enabled household-wide.
    op.add_column("cameras", sa.Column(
        "speaker_enabled", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("cameras", sa.Column("speaker_transport", sa.String(32), nullable=True))
    op.add_column("cameras", sa.Column("speaker_voice", sa.String(64), nullable=True))
    op.add_column("cameras", sa.Column(
        "speaker_volume", sa.Integer(), server_default="70", nullable=False))
    op.add_column("cameras", sa.Column("speaker_quiet_start", sa.String(5), nullable=True))
    op.add_column("cameras", sa.Column("speaker_quiet_end", sa.String(5), nullable=True))
    op.add_column("cameras", sa.Column(
        "speaker_cooldown_seconds", sa.Integer(), server_default="30", nullable=False))
    op.add_column("cameras", sa.Column(
        "speaker_daily_cap", sa.Integer(), server_default="50", nullable=False))
    op.add_column("cameras", sa.Column("speaker_endpoint", sa.String(1024), nullable=True))

    op.create_table(
        "speech_events",
        sa.Column(
            "id", sa.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "camera_id", sa.UUID(as_uuid=True),
            sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "rule_id", sa.UUID(as_uuid=True),
            sa.ForeignKey("rules.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "event_id", sa.UUID(as_uuid=True),
            sa.ForeignKey("events.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("trigger", sa.String(16), nullable=False, server_default="rule"),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("voice", sa.String(64), nullable=True),
        sa.Column("transport", sa.String(32), nullable=True),
        sa.Column("status", sa.String(16), nullable=False, server_default="queued"),
        sa.Column("suppressed_reason", sa.String(32), nullable=True),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("played_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.create_index("ix_speech_events_camera_id", "speech_events", ["camera_id"])
    # The daily cap counts today's rows per camera, so that pair is the
    # access path that matters.
    op.create_index(
        "ix_speech_events_camera_created", "speech_events", ["camera_id", "created_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_speech_events_camera_created", table_name="speech_events")
    op.drop_index("ix_speech_events_camera_id", table_name="speech_events")
    op.drop_table("speech_events")
    for column in (
        "speaker_endpoint", "speaker_daily_cap", "speaker_cooldown_seconds",
        "speaker_quiet_end", "speaker_quiet_start", "speaker_volume",
        "speaker_voice", "speaker_transport", "speaker_enabled",
    ):
        op.drop_column("cameras", column)
