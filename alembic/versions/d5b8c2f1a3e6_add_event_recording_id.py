"""add event recording_id

Footage link resolved at rule fire time.

Revision ID: d5b8c2f1a3e6
Revises: c3a7b1e9d2f4
Create Date: 2026-05-28 09:00:00.000000
"""
from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID

revision = "d5b8c2f1a3e6"
down_revision = "c3a7b1e9d2f4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("events", sa.Column("recording_id", UUID(as_uuid=True), nullable=True))
    op.create_index("ix_events_recording_id", "events", ["recording_id"])


def downgrade() -> None:
    op.drop_index("ix_events_recording_id", table_name="events")
    op.drop_column("events", "recording_id")
