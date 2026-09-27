"""Link transcript corrections to their source transcript (#261)."""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "f4b9c1d3e5a7"
down_revision: Union[str, None] = "f4a8c0b2d6e1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "audio_audit_log",
        sa.Column("transcript_id", postgresql.UUID(as_uuid=True), nullable=True),
    )
    op.create_foreign_key(
        "fk_audio_audit_log_transcript_id",
        "audio_audit_log",
        "transcripts",
        ["transcript_id"],
        ["id"],
        ondelete="SET NULL",
    )
    op.create_index("ix_audio_audit_log_transcript_id", "audio_audit_log", ["transcript_id"])


def downgrade() -> None:
    op.drop_index("ix_audio_audit_log_transcript_id", table_name="audio_audit_log")
    op.drop_constraint("fk_audio_audit_log_transcript_id", "audio_audit_log", type_="foreignkey")
    op.drop_column("audio_audit_log", "transcript_id")
