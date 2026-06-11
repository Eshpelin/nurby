"""alert/detection severity taxonomy on rules and events

Revision ID: d1e2f3a4b5c6
Revises: c0d1e2f3a4b5
Create Date: 2026-06-11 00:00:00.000000

Frigate-style triage split: "alert" rules are the push-worthy front-page
tier, "detection" rules are record-keeping behind a tab. Events carry
the severity stamped at fire time (demotable by a failed verify) plus a
denormalized camera_id so the alerts UI filters without parsing payload
JSON. Existing rows backfill as alerts with camera_id parsed from the
payload.
"""

from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects.postgresql import UUID

revision: str = "d1e2f3a4b5c6"
down_revision: Union[str, None] = "c0d1e2f3a4b5"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "rules",
        sa.Column("severity", sa.String(16), nullable=False, server_default="alert"),
    )
    op.add_column(
        "events",
        sa.Column("severity", sa.String(16), nullable=False, server_default="alert"),
    )
    op.add_column(
        "events",
        sa.Column("camera_id", UUID(as_uuid=True), nullable=True),
    )
    op.create_index(
        "ix_events_camera_id", "events", ["camera_id"], unique=False, if_not_exists=True
    )
    op.create_index(
        "ix_events_severity", "events", ["severity"], unique=False, if_not_exists=True
    )
    # Backfill camera_id from the JSON payload where it parses as a UUID.
    op.execute(
        """
        UPDATE events
        SET camera_id = (payload->>'camera_id')::uuid
        WHERE camera_id IS NULL
          AND payload->>'camera_id' ~ '^[0-9a-fA-F-]{36}$'
        """
    )


def downgrade() -> None:
    op.drop_index("ix_events_severity", table_name="events", if_exists=True)
    op.drop_index("ix_events_camera_id", table_name="events", if_exists=True)
    op.drop_column("events", "camera_id")
    op.drop_column("events", "severity")
    op.drop_column("rules", "severity")
