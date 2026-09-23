"""Native FTP recording backend (issue #269).

Adds the columns the buffer-then-upload pipeline needs: kind-specific
connection settings on ``storage_profiles`` (Fernet-sealed JSON — the
password never sits in clear) and the remote-tracking state on
``recordings`` (pending -> uploaded with retry bookkeeping, plus a
profile snapshot so retention can clean the remote even after the camera
moves to a different profile).
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

from alembic import op

revision = "c5d6e7f8a9b0"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("storage_profiles", sa.Column("config_enc", sa.Text(), nullable=True))
    op.add_column("recordings", sa.Column("remote_state", sa.String(16), nullable=True))
    op.add_column("recordings", sa.Column("remote_path", sa.String(1024), nullable=True))
    op.add_column("recordings", sa.Column("remote_profile_id", UUID(as_uuid=True), nullable=True))
    op.add_column(
        "recordings",
        sa.Column("remote_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("recordings", sa.Column("remote_error", sa.String(512), nullable=True))
    op.create_index(
        "ix_recordings_remote_state", "recordings", ["remote_state"], non_unique=True
    )


def downgrade() -> None:
    op.drop_index("ix_recordings_remote_state", table_name="recordings")
    op.drop_column("recordings", "remote_error")
    op.drop_column("recordings", "remote_attempts")
    op.drop_column("recordings", "remote_profile_id")
    op.drop_column("recordings", "remote_path")
    op.drop_column("recordings", "remote_state")
    op.drop_column("storage_profiles", "config_enc")
