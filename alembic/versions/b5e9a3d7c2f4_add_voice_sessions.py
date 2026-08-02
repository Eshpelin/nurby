"""spoken conversation sessions

Revision ID: b5e9a3d7c2f4
Revises: a2d6f9c4e7b8
Create Date: 2026-09-04 18:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'b5e9a3d7c2f4'
down_revision: Union[str, None] = 'a2d6f9c4e7b8'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "voice_sessions",
        sa.Column(
            "id", sa.UUID(as_uuid=True), primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column(
            "camera_id", sa.UUID(as_uuid=True),
            sa.ForeignKey("cameras.id", ondelete="CASCADE"), nullable=False,
        ),
        sa.Column(
            "conversation_id", sa.UUID(as_uuid=True),
            sa.ForeignKey("conversations.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column(
            "started_at", sa.DateTime(timezone=True),
            server_default=sa.func.now(), nullable=False,
        ),
        sa.Column("ended_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("ended_reason", sa.String(32), nullable=True),
        sa.Column("turns", sa.Integer(), server_default="0", nullable=False),
        sa.Column(
            "handed_off_to_user_id", sa.UUID(as_uuid=True),
            sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True,
        ),
        sa.Column("handed_off_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("refusals", sa.JSON(), nullable=True),
    )
    op.create_index("ix_voice_sessions_camera_id", "voice_sessions", ["camera_id"])
    op.create_index("ix_voice_sessions_started_at", "voice_sessions", ["started_at"])
    # Finding the live session for a camera is the hot path: every
    # incoming utterance asks "is one already open here?".
    op.create_index(
        "ix_voice_sessions_open", "voice_sessions", ["camera_id", "ended_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_voice_sessions_open", table_name="voice_sessions")
    op.drop_index("ix_voice_sessions_started_at", table_name="voice_sessions")
    op.drop_index("ix_voice_sessions_camera_id", table_name="voice_sessions")
    op.drop_table("voice_sessions")
