"""add push_devices (mobile FCM device registry)

Revision ID: c7e9a1b3d5f0
Revises: c7d9e1f3a5b7
Create Date: 2026-07-08 00:00:00.000000

Per-user FCM registration tokens so the mobile app can receive push
notifications. Token is unique: re-registering the same device re-assigns
the row to the current user instead of duplicating it. Rows cascade away
with their user; unregistered tokens are pruned by the dispatcher when
FCM reports them dead.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "c7e9a1b3d5f0"
down_revision: Union[str, None] = "c7d9e1f3a5b7"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "push_devices",
        sa.Column("id", sa.UUID(), nullable=False),
        sa.Column("user_id", sa.UUID(), nullable=False),
        sa.Column("platform", sa.String(length=16), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("app_version", sa.String(length=32), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.Column(
            "last_seen_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token"),
    )
    op.create_index("ix_push_devices_user_id", "push_devices", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_push_devices_user_id", table_name="push_devices")
    op.drop_table("push_devices")
