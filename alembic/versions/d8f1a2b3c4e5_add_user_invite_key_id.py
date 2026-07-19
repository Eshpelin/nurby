"""link users to the invite key they redeemed

Revision ID: d8f1a2b3c4e5
Revises: c7e9a1b3d5f0
Create Date: 2026-07-18 10:00:00.000000

Adds ``users.invite_key_id`` so an admin can see which invite key brought in
each account and when (the redemption time is the user's ``created_at``). The
FK is ON DELETE SET NULL: revoking/deleting a key must never cascade-delete
the accounts it created, it only drops the audit link.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "d8f1a2b3c4e5"
down_revision: Union[str, None] = "c7e9a1b3d5f0"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("invite_key_id", sa.UUID(), nullable=True),
    )
    op.create_index(
        "ix_users_invite_key_id", "users", ["invite_key_id"], unique=False
    )
    op.create_foreign_key(
        "fk_users_invite_key_id",
        "users",
        "invite_keys",
        ["invite_key_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_users_invite_key_id", "users", type_="foreignkey")
    op.drop_index("ix_users_invite_key_id", table_name="users")
    op.drop_column("users", "invite_key_id")
