"""per-camera STT accuracy knobs

Revision ID: d4f6a8c1e3b5
Revises: c3e5a7b9d1f4
Create Date: 2026-06-06 06:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'd4f6a8c1e3b5'
down_revision: Union[str, None] = 'c3e5a7b9d1f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Defaults match the prior hardcoded behavior, so existing cameras
    # transcribe identically until tuned.
    op.add_column(
        "cameras",
        sa.Column(
            "audio_stt_beam_size",
            sa.Integer(),
            server_default="1",
            nullable=False,
        ),
    )
    op.add_column(
        "cameras",
        sa.Column(
            "audio_stt_condition_on_previous_text",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )
    op.add_column(
        "cameras",
        sa.Column(
            "audio_stt_no_speech_threshold",
            sa.Float(),
            server_default="0.6",
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("cameras", "audio_stt_no_speech_threshold")
    op.drop_column("cameras", "audio_stt_condition_on_previous_text")
    op.drop_column("cameras", "audio_stt_beam_size")
