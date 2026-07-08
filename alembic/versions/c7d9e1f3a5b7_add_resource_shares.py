"""add resource_shares (anonymous scoped share links)

Revision ID: c7d9e1f3a5b7
Revises: a4c8e2d6f0b3
Create Date: 2026-07-05 12:00:00.000000

A ResourceShare is an anonymous, scoped, revocable link to ONE recorded
resource (a recording clip, an observation frame, an event, or a read-only
feed of one camera's past events). Only the SHA-256 hash of the token is
stored. Access ends on revoke, expiry, or when view_count reaches max_views.
Never live. Media reuses the normal serve paths so the system's selective
privacy blur is inherited automatically.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7d9e1f3a5b7"
down_revision: Union[str, None] = "a4c8e2d6f0b3"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "resource_shares",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column("recording_id", sa.UUID(), nullable=True),
        sa.Column("observation_id", sa.UUID(), nullable=True),
        sa.Column("event_id", sa.UUID(), nullable=True),
        sa.Column("camera_id", sa.UUID(), nullable=True),
        sa.Column("label", sa.String(length=200), nullable=True),
        sa.Column("created_by_id", sa.UUID(), nullable=True),
        sa.Column("max_views", sa.Integer(), nullable=True),
        sa.Column("view_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_accessed_ip", sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(["recording_id"], ["recordings.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["observation_id"], ["observations.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["event_id"], ["events.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["camera_id"], ["cameras.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["created_by_id"], ["users.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_resource_shares_token_hash", "resource_shares", ["token_hash"], unique=True)
    op.create_index("ix_resource_shares_recording_id", "resource_shares", ["recording_id"])
    op.create_index("ix_resource_shares_observation_id", "resource_shares", ["observation_id"])
    op.create_index("ix_resource_shares_event_id", "resource_shares", ["event_id"])
    op.create_index("ix_resource_shares_camera_id", "resource_shares", ["camera_id"])
    op.create_index("ix_resource_shares_created_by_id", "resource_shares", ["created_by_id"])


def downgrade() -> None:
    op.drop_index("ix_resource_shares_created_by_id", table_name="resource_shares")
    op.drop_index("ix_resource_shares_camera_id", table_name="resource_shares")
    op.drop_index("ix_resource_shares_event_id", table_name="resource_shares")
    op.drop_index("ix_resource_shares_observation_id", table_name="resource_shares")
    op.drop_index("ix_resource_shares_recording_id", table_name="resource_shares")
    op.drop_index("ix_resource_shares_token_hash", table_name="resource_shares")
    op.drop_table("resource_shares")
