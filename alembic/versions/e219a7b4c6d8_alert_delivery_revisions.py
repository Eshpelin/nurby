"""Link notifications to events and retain delivery revision timestamps (#219)."""

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision = "e219a7b4c6d8"
down_revision = ("b8d2f6a4c1e9", "d3f6a8c1e5b7")
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("event_id", UUID(as_uuid=True), nullable=True))
    op.create_index("ix_notifications_event_id", "notifications", ["event_id"], unique=False)
    op.create_foreign_key(
        "fk_notifications_event_id", "notifications", "events", ["event_id"], ["id"], ondelete="SET NULL"
    )
    op.add_column("notifications", sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))


def downgrade() -> None:
    op.drop_column("notifications", "updated_at")
    op.drop_constraint("fk_notifications_event_id", "notifications", type_="foreignkey")
    op.drop_index("ix_notifications_event_id", table_name="notifications")
    op.drop_column("notifications", "event_id")
