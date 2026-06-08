"""per-guardian notifications: user_id on notifications

Revision ID: d4e6f8a0b2c4
Revises: c9d2e4f6a1b3
Create Date: 2026-06-08

Adds a nullable user_id to notifications so guardian alerts can be fanned into a
private per-guardian inbox. Null preserves the existing household-wide feed.
"""

import sqlalchemy as sa
from alembic import op

revision = "d4e6f8a0b2c4"
down_revision = "c9d2e4f6a1b3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "notifications",
        sa.Column("user_id", sa.UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_notifications_user_id", "notifications", ["user_id"], unique=False
    )
    op.create_foreign_key(
        "fk_notifications_user_id",
        "notifications",
        "users",
        ["user_id"],
        ["id"],
        ondelete="CASCADE",
    )


def downgrade() -> None:
    op.drop_constraint("fk_notifications_user_id", "notifications", type_="foreignkey")
    op.drop_index("ix_notifications_user_id", table_name="notifications")
    op.drop_column("notifications", "user_id")
