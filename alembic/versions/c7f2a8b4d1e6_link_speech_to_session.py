"""link a spoken line to its conversation session

Revision ID: c7f2a8b4d1e6
Revises: b5e9a3d7c2f4
Create Date: 2026-09-05 10:00:00.000000
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = 'c7f2a8b4d1e6'
down_revision: Union[str, None] = 'b5e9a3d7c2f4'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Nullable because most speech is not part of a conversation. A rule
    # announcement has no session, and backfilling one would invent a
    # relationship that never existed.
    op.add_column(
        "speech_events",
        sa.Column("session_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_speech_events_session_id", "speech_events", "voice_sessions",
        ["session_id"], ["id"], ondelete="CASCADE",
    )
    # Reading a session's transcript is the access path this exists for.
    op.create_index(
        "ix_speech_events_session_id", "speech_events", ["session_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_speech_events_session_id", table_name="speech_events")
    op.drop_constraint(
        "fk_speech_events_session_id", "speech_events", type_="foreignkey"
    )
    op.drop_column("speech_events", "session_id")
